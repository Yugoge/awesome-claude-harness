"""7. prose-only: a test that asserts only that text is present in a doc and runs no code.

Doc text is text that comes from a string literal naming a `*.md` file, `commands/`,
`agents/`, `skills/`, `templates/` or CLAUDE.md. The check follows it through assignments,
loops, `with`, comprehensions, local helpers (of the test file or of a pure-text helper
module it imports), fixtures (the test file's and its conftest.py's) and parametrize values.
Output of code is not doc text, and a structural parse (json, YAML, TOML, csv, ast, or a
local helper whose name says it parses: parse, table, rows, front matter) ends it: an
assertion on parsed structure is not text presence.

A test is reported when it has at least one assertion, every assertion (its own, or one in
a helper or fixture it uses) depends on doc text, and either

- it exercises no code: no name bound to an import outside the standard library, pytest,
  the parsers above and pure-text helper modules of this tree, and no subprocess,
  importlib, runpy, os.system/os.popen, exec or eval call; or
- it exercises code, but no code it runs is a consumer of the asserted doc. A consumer is
  the file a call, import or subprocess resolves to; it consumes the doc when its source,
  or the source of a module of this tree it imports, names the doc by basename or by
  directory. A call or subprocess whose file cannot be resolved fails closed: the test is
  reported, naming the unresolved target.

There is no list of exempt tests. A sentence no code consumes is not a contract: its test
runs the component that enforces the rule, or goes.
"""
from __future__ import annotations

import ast
import functools
import gc
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field

from .tree import Finding, Tree

CHECK = "prose-only"
DOC_DIRS = ("commands", "agents", "skills", "templates")
_PATHLIKE = re.compile(r"^[\w.\-/${}~:*]+$")
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test)\.py$")
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"pytest", "_pytest", "__future__"}
# Modules that only parse text into structure. yaml is not stdlib, but it runs no harness code.
PARSERS = {"json", "yaml", "tomllib", "tomli", "csv", "ast", "configparser", "xml", "email"}
# Modules whose calls run code (another process, or a module loaded by path or name).
RUNNERS = {"subprocess", "importlib", "runpy", "multiprocessing", "pty"}
OS_RUNNERS = {"system", "popen", "execv", "execve", "execvp", "execl", "execlp", "spawnv", "spawnl", "posix_spawn",
              "startfile"}
STRUCT_HELPER = re.compile(r"parse|table|rows|front_?matter|yaml|json|toml", re.I)
BUILTIN_FIXTURES = {"tmp_path", "tmp_path_factory", "tmpdir", "monkeypatch", "capsys", "capfd", "caplog",
                    "request", "recwarn", "pytestconfig", "capsysbinary", "capfdbinary", "doctest_namespace"}
MAX_PATHS = 24


@functools.lru_cache(maxsize=None)
def names_doc(s: str) -> bool:
    """True when the literal names a doc: a *.md file, CLAUDE.md, or a prompt folder."""
    if not s or len(s) > 300 or not _PATHLIKE.match(s):
        return False
    base = s.rsplit("/", 1)[-1]
    if base.endswith(".md") and len(base) > 3 or "CLAUDE.md" in s or s in DOC_DIRS:
        return True
    return any(p in DOC_DIRS for p in s.split("/")[:-1])


def _norm(p: str) -> str | None:
    p = posixpath.normpath(p)
    if p.startswith("..") or p.startswith("/"):
        return None
    return p


def _join(a: str, b: str) -> str | None:
    return _norm(posixpath.join(a, b))


def _product(xs, ys, fn) -> tuple:
    out = []
    for x in xs:
        for y in ys:
            r = fn(x, y)
            if r is not None and r not in out:
                out.append(r)
            if len(out) >= MAX_PATHS:
                return tuple(out)
    return tuple(out)


@dataclass(frozen=True)
class Target:
    """What a test runs: a label for the message, and the tree file it resolves to (None: unresolved)."""
    label: str
    file: str | None


@dataclass
class Val:
    taint: frozenset = frozenset()     # the docs this value names (a path, a folder, a glob)
    paths: tuple = ()                  # tree-relative path strings this value may be
    text: frozenset = frozenset()      # the docs whose text this value carries


def _text(*vals) -> frozenset:
    return frozenset().union(*(v.text for v in vals))


def _union(vals) -> "Val":
    return Val(frozenset().union(*(v.taint for v in vals)), (), _text(*vals))


# Methods that read a file: their result carries the text of the docs the receiver names.
READS = {"read_text", "read_bytes", "read", "readlines", "readline", "open"}


NONE = Val()


def _joined(first: Val, rest) -> Val:
    """A path join: where the joined path names a doc, it replaces the literals it was built from."""
    paths, taint = first.paths, set(first.taint) - set(first.paths)
    for v in rest:
        paths = _product(paths, v.paths, _join) if paths and v.paths else ()
        taint |= set(v.taint) - set(v.paths)
    docs = {p for p in paths if names_doc(p)}
    if not paths:
        taint |= first.taint
        for v in rest:
            taint |= v.taint
    return Val(frozenset(taint | docs), paths, _text(first, *rest))


@dataclass
class Result:
    asserts: list = field(default_factory=list)      # (lineno, frozenset of doc literals or empty)
    code: bool = False
    events: int = 0                                  # code runs seen, to tell which value came from code
    targets: list = field(default_factory=list)
    ret: Val = field(default_factory=Val)


class Index:
    """The tree's python files, the modules they are, and what is pure text."""

    def __init__(self, tree: Tree):
        self.tree = tree
        self.files = _tree_files(tree)
        self.fileset = set(self.files)
        self.by_base: dict[str, list[str]] = {}
        for f in self.files:
            self.by_base.setdefault(posixpath.basename(f), []).append(f)
        self.modules: dict[str, "Module | None"] = {}
        self._pure: dict[str, bool] = {}
        self._source_names: dict[str, str] = {}
        self._resolved: dict = {}

    # ------------------------------------------------------------ files

    def file_of_path(self, p: str) -> str | None:
        """The tree file a path string names, by exact path, harness-home path or unique basename."""
        for cand in (p, re.sub(r"^.*?\.claude/", "", p), re.sub(r"^.*\}/", "", p)):
            n = _norm(cand.strip("\"'")) if cand else None
            if n and n in self.fileset:
                return n
        base = posixpath.basename(p.strip("\"'"))
        if base.endswith((".py", ".sh")) and len(self.by_base.get(base, ())) == 1:
            return self.by_base[base][0]
        return None

    def resolve_module(self, here: str, dotted: str, level: int) -> str | None:
        key = (here, dotted, level)
        if key not in self._resolved:
            self._resolved[key] = self._resolve_module(here, dotted, level)
        return self._resolved[key]

    def _resolve_module(self, here: str, dotted: str, level: int) -> str | None:
        parts = [x for x in dotted.split(".") if x]
        rel = "/".join(parts)
        bases = []
        if level:
            base = here
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            bases = [base]
        else:
            bases = [here, ""]
        for b in bases:
            for cand in (posixpath.join(b, rel + ".py"), posixpath.join(b, rel, "__init__.py")):
                n = _norm(cand)
                if n and n in self.fileset:
                    return n
        if level or not parts:
            return None
        # a sys.path entry the test adds: the unique file of that name in the tree
        hits = [f for f in self.by_base.get(parts[-1] + ".py", []) + self.by_base.get("__init__.py", [])
                if f.endswith("/" + rel + ".py") or f.endswith("/" + rel + "/__init__.py")]
        return hits[0] if len(hits) == 1 else None

    def classify_import(self, here: str, dotted: str, level: int) -> tuple[str, str | None]:
        """('std' | 'parser' | 'text' | 'code', file): what binding a name to this module means."""
        top = dotted.split(".")[0] if dotted else ""
        if not level and top in STDLIB:
            return ("runner" if top in RUNNERS else "std"), None
        if not level and top in PARSERS:
            return "parser", None
        f = self.resolve_module(here, dotted, level)
        if f and "tests" in f.split("/")[:-1] and self.pure_text(f):
            return "text", f
        return "code", f

    def pure_text(self, rel: str) -> bool:
        if rel in self._pure:
            return self._pure[rel]
        self._pure[rel] = True               # a cycle is judged by the rest of the cycle
        mod = self.module(rel)
        ok = mod is not None and mod.pure and not any(
            isinstance(c, ast.Call) and _runs_code_by_name(c, mod.imports) for c in ast.walk(mod.ast))
        self._pure[rel] = ok
        return ok

    def module(self, rel: str) -> "Module | None":
        if rel not in self.modules:
            self.modules[rel] = None
            try:
                src = self.tree.read(rel)
                self.modules[rel] = Module(self, rel, ast.parse(src), src)
            except (SyntaxError, ValueError, OSError):
                pass
        return self.modules[rel]

    def names(self, rel: str, doc: str) -> bool:
        """The consumer file, or a module of this tree it imports, names the doc."""
        text = self._consumer_text(rel)
        base = posixpath.basename(doc.rstrip("/"))
        if "*" not in base and base and base in text:
            return True
        d = posixpath.dirname(doc.rstrip("/")) if "*" not in base and base.endswith(".md") else doc.rstrip("/")
        d = d.split("*")[0].rstrip("/")
        d = re.sub(r"^.*?\.claude/", "", d)
        if not d or d == ".":
            return False
        return re.search(r"""(?:["'/]|^)""" + re.escape(d) + r"""(?:/|["'])""", text, re.M) is not None

    def _consumer_text(self, rel: str) -> str:
        if rel in self._source_names:
            return self._source_names[rel]
        seen, todo, chunks = set(), [(rel, 0)], []
        while todo:
            f, depth = todo.pop()
            if f in seen:
                continue
            seen.add(f)
            try:
                text = self.tree.read(f)
            except OSError:
                continue
            chunks.append(text)
            if depth >= 3 or not f.endswith(".py"):
                continue
            mod = self.module(f)
            for dep in (mod.local_imports if mod else ()):
                todo.append((dep, depth + 1))
        self._source_names[rel] = "\n".join(chunks)
        return self._source_names[rel]


def _tree_files(tree: Tree) -> list[str]:
    try:
        proc = subprocess.run(["git", "-C", str(tree.root), "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard"], capture_output=True, timeout=60)
        if proc.returncode == 0:
            out = sorted({p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p})
            return [p for p in out if (tree.root / p).is_file()]
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for dirpath, dirs, files in os.walk(tree.root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            out.append(os.path.relpath(os.path.join(dirpath, name), tree.root).replace(os.sep, "/"))
    return out


class Module:
    """One python file: its imports, top-level functions and fixtures, and its module-level values."""

    def __init__(self, index: Index, rel: str, mod: ast.Module, source: str = ""):
        self.index, self.rel, self.ast = index, rel, mod
        self.here = posixpath.dirname(rel)
        self.imports: dict[str, tuple[str, str | None, str]] = {}   # name -> (kind, file, dotted)
        self.funcs: dict[str, ast.FunctionDef] = {}
        self.fixtures: dict[str, ast.FunctionDef] = {}
        self.local_imports: list[str] = []
        self.pure = True
        self.docs = False
        for node in mod.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
                if _is_fixture(node):
                    self.fixtures[_fixture_name(node)] = node
        top = set(map(id, _module_level(mod)))
        for node in _statements(mod):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name, kind, f, dotted in self._bindings(node):
                    if id(node) in top:
                        self.imports[name] = (kind, f, dotted)
                    if kind in ("code", "runner"):
                        self.pure = False
                    if f and f not in self.local_imports:
                        self.local_imports.append(f)
        # a superset test, enough to skip a module no doc literal can reach
        self.docs = _DOC_HINT.search(source) is not None
        self.ctx_cache: dict = {}
        self._in_progress: set = set()
        self._env: Env | None = None
        self._reach: bool | None = None

    @property
    def env(self) -> "Env":
        """The module-level values, interpreted on first use."""
        if self._env is None:
            self._env = Env()
            ctx = Ctx(self, self._env, Result())
            body = [s for s in self.ast.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            for _ in range(_passes(body)):
                ctx.block(body)
        return self._env

    def reaches_docs(self) -> bool:
        """A doc literal is in this module or in a test helper module it imports: only then can doc text arise."""
        if self._reach is None:
            self._reach = self.docs
            if not self.docs:
                for f in self.local_imports:
                    sub = self.index.module(f) if "tests" in f.split("/")[:-1] else None
                    if sub is not None and sub.reaches_docs():
                        self._reach = True
                        break
        return self._reach

    def _bindings(self, node):
        if isinstance(node, ast.Import):
            for a in node.names:
                kind, f = self.index.classify_import(self.here, a.name, 0)
                yield (a.asname or a.name.split(".")[0]), kind, f, a.name
        else:
            base = node.module or ""
            for a in node.names:
                if a.name == "*":
                    continue
                sub = f"{base}.{a.name}" if base else a.name
                kind, f = self.index.classify_import(self.here, sub, node.level)
                if f is None and kind == "code":
                    kind, f = self.index.classify_import(self.here, base, node.level) if base else (kind, f)
                yield (a.asname or a.name), kind, f, sub

    # ------------------------------------------------------------ helper analysis

    def call_helper(self, name: str, args: dict) -> Result:
        """A top-level function of this module run with these argument values (doc taint, paths)."""
        fn = self.funcs.get(name)
        if fn is None:
            return Result()
        key = (name, tuple(sorted((k, v.taint, v.paths, v.text) for k, v in args.items())))
        if key in self.ctx_cache:
            return self.ctx_cache[key]
        # A function already being run is not run again inside itself, whatever its arguments: a
        # recursive helper whose arguments grow at each level (cli_shapes._walk's key path) would
        # otherwise be run again with new values until the interpreter's stack runs out.
        if any(running == name for running, _args in self._in_progress):
            return Result()
        self._in_progress.add(key)
        res = run_function(self, fn, args)
        self._in_progress.discard(key)
        self.ctx_cache[key] = res
        return res


_DOC_HINT = re.compile(r"\.md\b|\b(?:commands|agents|skills|templates)\b")


def _statements(mod: ast.Module):
    """Every statement of the module, in function and class bodies too (expressions are not walked)."""
    todo = list(mod.body)
    while todo:
        node = todo.pop()
        yield node
        for name in ("body", "orelse", "finalbody", "handlers", "cases"):
            for child in getattr(node, name, ()) or ():
                if isinstance(child, (ast.stmt, ast.excepthandler)) or child.__class__.__name__ == "match_case":
                    todo.append(child)


def _passes(body) -> int:
    """Two passes when a loop can carry a value back to an earlier statement, else one."""
    if not body:
        return 1
    n = getattr(body[0], "_prose_passes", None)
    if n is None:
        n = _count_passes(body)
        body[0]._prose_passes = n
    return n


def _count_passes(body) -> int:
    todo = list(body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            return 2
        for name in ("body", "orelse", "finalbody", "handlers"):
            todo.extend(c for c in getattr(node, name, ()) or () if isinstance(c, (ast.stmt, ast.excepthandler)))
    return 1


def _module_level(mod: ast.Module):
    """The module's statements outside function and class bodies (an import under `if` or `try` included)."""
    todo = list(mod.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt) or isinstance(child, ast.excepthandler):
                todo.append(child)


def _is_fixture(fn) -> bool:
    for d in fn.decorator_list:
        f = d.func if isinstance(d, ast.Call) else d
        if isinstance(f, ast.Attribute) and f.attr == "fixture" or isinstance(f, ast.Name) and f.id == "fixture":
            return True
    return False


def _fixture_name(fn) -> str:
    for d in fn.decorator_list:
        if isinstance(d, ast.Call):
            for k in d.keywords:
                if k.arg == "name" and isinstance(k.value, ast.Constant):
                    return str(k.value.value)
    return fn.name


def _counting(call: ast.Call) -> bool:
    """count / find / index of text, or len() of a regex findall: compared with a number."""
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in ("count", "find", "rfind", "index", "rindex"):
        return True
    return isinstance(f, ast.Name) and f.id == "len" and len(call.args) == 1 and isinstance(call.args[0], ast.Call) \
        and isinstance(call.args[0].func, ast.Attribute) and call.args[0].func.attr in ("findall", "finditer")


def _is_search(node) -> bool:
    """A regex search, match or findall (or a group of one): its truthiness is text presence."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("group", "groups"):
        node = node.func.value
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
        "search", "match", "fullmatch", "findall")


def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _runs_code_by_name(call: ast.Call, imports: dict) -> bool:
    d = _dotted(call.func)
    if not d:
        return False
    head, _, rest = d.partition(".")
    if head in imports:
        d = imports[head][2] + ("." + rest if rest else "")
    top = d.split(".")[0]
    if top in RUNNERS:
        return True
    if top == "os" and d.split(".")[-1] in OS_RUNNERS:
        return True
    return d in ("exec", "eval", "__import__")


class Env:
    def __init__(self, parent: "Env | None" = None):
        self.parent = parent
        self.taint: dict[str, frozenset] = {}
        self.text: dict[str, frozenset] = {}
        self.matches: dict[str, bool] = {}   # names bound to a regex search or a plain selection of doc text
        self.paths: dict[str, tuple] = {}
        self.code: dict[str, list] = {}     # name -> targets of the code its value came from
        self.imports: dict[str, tuple] = {}

    def lookup(self, attr: str, name: str):
        e = self
        while e is not None:
            d = getattr(e, attr)
            if name in d:
                return d[name]
            e = e.parent
        return None


def run_function(module: Module, fn, args: dict) -> Result:
    env = Env(module.env)
    for k, v in args.items():
        env.taint[k] = v.taint
        env.text[k] = v.text
        env.paths[k] = v.paths
    res = Result()
    ctx = Ctx(module, env, res)
    for i in range(_passes(fn.body)):
        if i:
            res.asserts.clear()
            res.targets.clear()
            res.code = False
            res.ret = Val()
        ctx.block(fn.body)
    return res


class Ctx:
    """Abstract interpretation of a block: doc taint, path strings, code run, assertions."""

    def __init__(self, module: Module, env: Env, res: Result):
        self.m, self.env, self.res = module, env, res
        self._last_targets: list = []

    # ------------------------------------------------------------ recording

    def code(self, targets):
        self.res.code = True
        self.res.events += 1
        self._last_targets = list(targets)
        for t in targets:
            if t not in self.res.targets:
                self.res.targets.append(t)

    def merge(self, sub: Result):
        self.res.asserts.extend(sub.asserts)
        if sub.code:
            self.code(sub.targets)

    # ------------------------------------------------------------ statements

    def block(self, stmts):
        for s in stmts:
            self.stmt(s)

    def bind(self, target, val: Val, code_targets=None):
        if isinstance(target, ast.Name):
            e = self.env
            e.taint[target.id] = e.taint.get(target.id, frozenset()) | val.taint
            e.text[target.id] = e.text.get(target.id, frozenset()) | val.text
            e.paths[target.id] = val.paths
            if code_targets is not None:
                e.code[target.id] = code_targets
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t in target.elts:
                self.bind(t, Val(val.taint, (), val.text), code_targets)
        elif isinstance(target, ast.Starred):
            self.bind(target.value, val, code_targets)
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            base = target.value
            while isinstance(base, (ast.Subscript, ast.Attribute)):
                base = base.value
            self.expr(target)
            if isinstance(base, ast.Name) and (val.taint or val.text):
                self.env.taint[base.id] = self.env.taint.get(base.id, frozenset()) | val.taint
                self.env.text[base.id] = self.env.text.get(base.id, frozenset()) | val.text

    def assign(self, targets, value):
        before, n_targets = self.res.events, len(self.res.targets)
        val = self.expr(value)
        code_targets = None
        if self.res.events > before:
            code_targets = self._targets_since(n_targets)
        for t in targets:
            self.bind(t, val, code_targets)
            if isinstance(t, ast.Name) and val.text and (_is_search(value) or not self._calls_helper(value)):
                self.env.matches[t.id] = True

    def _calls_helper(self, node) -> bool:
        """The value runs logic of the test's own: a call of one of its module's functions."""
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in self.m.funcs
                   for c in ast.walk(node))

    def _targets_since(self, n_targets: int) -> list:
        """The targets of the code run since a snapshot (a re-run of a known target included)."""
        new = list(self.res.targets[n_targets:])
        return new or list(self._last_targets)

    def stmt(self, s):
        if isinstance(s, ast.Assign):
            self.assign(s.targets, s.value)
        elif isinstance(s, (ast.AnnAssign, ast.AugAssign)):
            if s.value is not None:
                self.assign([s.target], s.value)
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            it = self.expr(s.iter)
            self.bind(s.target, it)
            self.block(s.body)
            self.block(s.orelse)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for item in s.items:
                v = self.expr(item.context_expr)
                if item.optional_vars is not None:
                    self.bind(item.optional_vars, Val(v.taint, (), v.text))
            self.block(s.body)
        elif isinstance(s, (ast.If, ast.While)):
            self.expr(s.test)
            self.block(s.body)
            self.block(s.orelse)
        elif isinstance(s, ast.Try) or s.__class__.__name__ == "TryStar":
            self.block(s.body)
            for h in s.handlers:
                self.block(h.body)
            self.block(s.orelse)
            self.block(s.finalbody)
        elif isinstance(s, ast.Expr):
            self.expr(s.value)
        elif isinstance(s, ast.Return):
            if s.value is not None:
                v = self.expr(s.value)
                self.res.ret = Val(self.res.ret.taint | v.taint, v.paths or self.res.ret.paths, self.res.ret.text | v.text)
        elif isinstance(s, ast.Assert):
            self.expr(s.test)
            if s.msg is not None:
                self.expr(s.msg)
            self.res.asserts.append((s.lineno, self.presence(s.test) or frozenset()))
        elif isinstance(s, ast.Raise):
            if s.exc is not None:
                self.expr(s.exc)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.block(s.body)                  # a nested helper: judged as part of the test
        elif isinstance(s, (ast.Import, ast.ImportFrom)):
            for name, kind, f, dotted in self.m._bindings(s):
                self.env.imports[name] = (kind, f, dotted)
                if kind == "code":
                    self.code([Target(dotted, f)])
        elif s.__class__.__name__ == "Match":
            self.expr(s.subject)
            for case in s.cases:
                self.block(case.body)

    # ------------------------------------------------------------ text presence

    def presence(self, e) -> frozenset | None:
        """The docs an assertion tests for text presence in, or None when it tests anything else.

        Text presence is `in` / `not in` on doc text, a regex search or match over it, its
        startswith / endswith / count / find / index, the truthiness of doc text (a match), and
        and / or / not / all / any of these."""
        if isinstance(e, ast.BoolOp):
            parts = [self.presence(v) for v in e.values]
            return None if any(p is None for p in parts) else frozenset().union(*parts)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            return self.presence(e.operand)
        if isinstance(e, ast.Compare):
            if len(e.ops) == 1 and isinstance(e.ops[0], (ast.In, ast.NotIn)):
                text = self.expr(e.comparators[0]).text
                return text or None
            sides = [e.left] + list(e.comparators)
            counts = [x for x in sides if isinstance(x, ast.Call) and _counting(x)]
            if counts and all(isinstance(x, (ast.Constant, ast.UnaryOp)) or x in counts for x in sides):
                parts = [self.presence(x) for x in counts]
                return None if any(p is None for p in parts) else frozenset().union(*parts)
            return None
        if isinstance(e, ast.Call):
            f = e.func
            if isinstance(f, ast.Name) and f.id in ("all", "any", "bool") and len(e.args) == 1:
                arg = e.args[0]
                if isinstance(arg, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
                    self.expr(arg)
                    return self.presence(arg.elt)
                return self.presence(arg)
            if isinstance(f, ast.Name) and f.id == "len" and len(e.args) == 1:
                return self.presence(e.args[0])
            if isinstance(f, ast.Attribute):
                if f.attr in ("startswith", "endswith", "count", "find", "rfind", "index", "rindex", "__contains__"):
                    return self.expr(f.value).text or None
                if f.attr in ("search", "match", "fullmatch", "findall", "finditer"):
                    text = _text(*(self.expr(a) for a in e.args))
                    return text or None
            return None
        if isinstance(e, ast.Name) and self.env.lookup("matches", e.id):
            return self.expr(e).text or None
        return None

    # ------------------------------------------------------------ expressions

    def import_of(self, name: str):
        hit = self.env.lookup("imports", name)
        if hit is None:
            hit = self.m.imports.get(name)
        return hit

    def expr(self, n) -> Val:
        if n is None:
            return NONE
        if isinstance(n, ast.Constant):
            if isinstance(n.value, str):
                return Val(frozenset([n.value]) if names_doc(n.value) else frozenset(), (n.value,))
            return NONE
        if isinstance(n, ast.Name):
            return self.name(n.id)
        if isinstance(n, ast.Call):
            return self.call(n)
        if isinstance(n, ast.Attribute):
            v = self.expr(n.value)
            if n.attr == "parent":
                return Val(v.taint, tuple(p for p in (_norm(posixpath.dirname(x) or ".") for x in v.paths) if p),
                           v.text)
            if n.attr == "name":
                return Val(v.taint, tuple(posixpath.basename(x) for x in v.paths), v.text)
            return Val(v.taint, (), v.text)
        if isinstance(n, ast.Subscript):
            v = self.expr(n.value)
            self.expr(n.slice)
            if isinstance(n.value, ast.Attribute) and n.value.attr == "parents" and isinstance(n.slice, ast.Constant) \
                    and isinstance(n.slice.value, int):
                out = []
                for p in self.expr(n.value.value).paths:
                    for _ in range(n.slice.value + 1):
                        p = posixpath.dirname(p)
                    out.append(_norm(p or "."))
                return Val(v.taint, tuple(p for p in out if p), v.text)
            return Val(v.taint, (), v.text)
        if isinstance(n, ast.BinOp):
            a, b = self.expr(n.left), self.expr(n.right)
            if isinstance(n.op, ast.Div):
                return _joined(a, [b])
            paths = _product(a.paths, b.paths, lambda x, y: x + y) if isinstance(n.op, ast.Add) else ()
            return Val(a.taint | b.taint, paths, a.text | b.text)
        if isinstance(n, ast.JoinedStr):
            taint, text, acc = frozenset(), frozenset(), ("",)
            for part in n.values:
                if isinstance(part, ast.Constant):
                    acc = tuple(x + str(part.value) for x in acc)
                else:
                    v = self.expr(part.value)
                    taint |= v.taint
                    text |= v.text
                    acc = _product(acc, v.paths, lambda x, y: x + y) if v.paths else ()
            taint |= {p for p in acc if names_doc(p)}
            return Val(taint, acc, text)
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            vals = [self.expr(e) for e in n.elts]
            return Val(frozenset().union(*(v.taint for v in vals)), tuple(p for v in vals for p in v.paths)[:MAX_PATHS],
                       _text(*vals))
        if isinstance(n, ast.Dict):
            for k in n.keys:
                self.expr(k)
            vals = [self.expr(v) for v in n.values]
            return Val(frozenset().union(*(v.taint for v in vals)), tuple(p for v in vals for p in v.paths)[:MAX_PATHS],
                       _text(*vals))
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for g in n.generators:
                it = self.expr(g.iter)
                self.bind(g.target, it)
                for c in g.ifs:
                    self.expr(c)
            if isinstance(n, ast.DictComp):
                k, v = self.expr(n.key), self.expr(n.value)
                return Val(k.taint | v.taint, (), k.text | v.text)
            v = self.expr(n.elt)
            return Val(v.taint, v.paths, v.text)
        if isinstance(n, ast.IfExp):
            self.expr(n.test)
            a, b = self.expr(n.body), self.expr(n.orelse)
            return Val(a.taint | b.taint, a.paths + b.paths, a.text | b.text)
        if isinstance(n, (ast.BoolOp, ast.Compare)):
            vals = [self.expr(e) for e in (n.values if isinstance(n, ast.BoolOp) else [n.left] + n.comparators)]
            paths = tuple(p for v in vals for p in v.paths) if isinstance(n, ast.BoolOp) else ()
            return Val(frozenset().union(*(v.taint for v in vals)), paths, _text(*vals))
        if isinstance(n, ast.UnaryOp):
            v = self.expr(n.operand)
            return Val(v.taint, (), v.text)
        if isinstance(n, ast.Lambda):
            v = self.expr(n.body)
            return Val(v.taint, (), v.text)
        if isinstance(n, (ast.Starred, ast.Await, ast.FormattedValue, ast.NamedExpr)):
            v = self.expr(n.value)
            if isinstance(n, ast.NamedExpr):
                self.bind(n.target, v)
            return v
        if isinstance(n, (ast.Yield, ast.YieldFrom)):
            v = self.expr(n.value)
            self.res.ret = Val(self.res.ret.taint | v.taint, v.paths or self.res.ret.paths, self.res.ret.text | v.text)
            return NONE
        if isinstance(n, ast.Slice):
            for e in (n.lower, n.upper, n.step):
                self.expr(e)
            return NONE
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.expr):
                self.expr(child)
        return NONE

    def name(self, name: str) -> Val:
        if name == "__file__":
            return Val(frozenset(), (self.m.rel,))
        code = self.env.lookup("code", name)
        if code is not None:
            self.code(code)
        local = self.env.lookup("taint", name)
        imp = self.import_of(name) if local is None else None
        if imp is not None and imp[0] == "code":
            self.code([Target(imp[2], imp[1])])
        return Val(local or frozenset(), self.env.lookup("paths", name) or (), self.env.lookup("text", name) or frozenset())

    # ------------------------------------------------------------ calls

    def call(self, n: ast.Call) -> Val:
        argv = [self.expr(a) for a in n.args]
        kwv = {k.arg: self.expr(k.value) for k in n.keywords}
        allv = argv + list(kwv.values())
        f = n.func
        dotted = _dotted(f)
        if isinstance(f, ast.Name):
            return self.call_name(n, f.id, argv, kwv, allv)
        if dotted:
            head, _, rest = dotted.partition(".")
            imp = self.import_of(head) if self.env.lookup("taint", head) is None else None
            if imp is not None:
                kind = imp[0]
                if kind == "code":
                    self.code([Target(imp[2], imp[1])])
                    return NONE
                if kind == "text" and imp[1]:
                    mod = self.m.index.module(imp[1])
                    if mod is not None and rest in mod.funcs:
                        return self.helper(mod, rest, n, argv, kwv)
                    return _union(allv)
                return self.call_std(n, imp[2] + "." + rest, argv, kwv, allv)
            if head == "self" and rest.startswith("assert"):
                presence = rest in ("assertIn", "assertNotIn", "assertRegex", "assertNotRegex", "assertTrue",
                                    "assertFalse", "assertIsNotNone")
                self.res.asserts.append((n.lineno, _text(*allv) if presence else frozenset()))
                return NONE
            if head in ("os", "sys", "subprocess", "importlib", "runpy", "json", "re", "posixpath"):
                return self.call_std(n, dotted, argv, kwv, allv)
        # a method on a value; a method of a value code produced is code, and its result is not doc text
        before = self.res.events
        recv = self.expr(f.value) if isinstance(f, ast.Attribute) else self.expr(f)
        if self.res.events > before:
            return NONE
        meth = f.attr if isinstance(f, ast.Attribute) else ""
        u = _union([recv] + allv)
        if meth in READS:
            return Val(u.taint, (), u.text | recv.taint)
        if meth in ("resolve", "absolute", "expanduser", "strip", "rstrip", "lstrip"):
            return Val(u.taint, recv.paths, u.text)
        if meth == "joinpath":
            return _joined(recv, argv)
        if meth in ("glob", "rglob", "iterdir"):
            return Val(u.taint | recv.taint, (), u.text)
        if meth in ("loads", "load", "safe_load", "safe_load_all", "load_all", "parse", "literal_eval", "reader",
                    "DictReader"):
            return NONE
        return u

    def call_name(self, n, name, argv, kwv, allv) -> Val:
        if self.env.lookup("taint", name) is None and self.env.lookup("paths", name) is None:
            code = self.env.lookup("code", name)
            if code is not None:
                self.code(code)
                return NONE
            imp = self.import_of(name)
            if imp is not None:
                kind, f, dotted = imp
                if kind == "code":
                    self.code([Target(dotted, f)])
                    return NONE
                if kind == "text" and f:
                    mod = self.m.index.module(f)
                    leaf = dotted.rsplit(".", 1)[-1]
                    if mod is not None and leaf in mod.funcs:
                        return self.helper(mod, leaf, n, argv, kwv)
                    return _union(allv)
                return self.call_std(n, dotted, argv, kwv, allv)
            if name in self.m.funcs:
                return self.helper(self.m, name, n, argv, kwv)
        if name in ("exec", "eval", "__import__", "compile"):
            self.code([Target(name, None)])
            return NONE
        if name == "open":
            u = _union(allv)
            return Val(u.taint, (), u.text | (argv[0].taint if argv else frozenset()))
        if name in ("str", "Path", "PurePath", "PosixPath"):
            return _joined(argv[0], argv[1:]) if argv else NONE
        u = _union(allv)
        if name in ("list", "tuple", "sorted", "set", "frozenset", "reversed"):
            return Val(u.taint, tuple(p for v in argv for p in v.paths)[:MAX_PATHS], u.text)
        return Val(u.taint, (), u.text)

    def helper(self, mod: Module, name: str, n, argv, kwv) -> Val:
        fn = mod.funcs[name]
        params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        args = dict(zip(params, argv))
        args.update({k: v for k, v in kwv.items() if k})
        res = mod.call_helper(name, args)
        self.merge(res)
        if STRUCT_HELPER.search(name):
            return NONE
        return res.ret

    def call_std(self, n, full: str, argv, kwv, allv) -> Val:
        parts = full.split(".")
        top, leaf = parts[0], parts[-1]
        if top == "subprocess" or (top == "os" and leaf in OS_RUNNERS) or top in ("multiprocessing", "pty"):
            self.code(self.targets_of(full, argv[:1] + [kwv.get("args", NONE)] if argv else list(kwv.values())))
            return NONE
        if top == "importlib":
            if leaf == "spec_from_file_location":
                self.code(self.targets_of(full, argv[1:2] or [kwv.get("location", NONE)]))
            elif leaf == "import_module":
                self.code(self.module_targets(full, argv[:1]))
            else:
                self.code([])
            return NONE
        if top == "runpy":
            if leaf == "run_path":
                self.code(self.targets_of(full, argv[:1]))
            else:
                self.code(self.module_targets(full, argv[:1]))
            return NONE
        if top in PARSERS:
            return NONE
        if full in ("os.path.join", "posixpath.join", "os.path.abspath", "os.path.realpath", "os.path.normpath",
                    "os.fspath", "pathlib.Path", "pathlib.PurePath", "os.path.expanduser"):
            return _joined(argv[0], argv[1:]) if argv else NONE
        u = _union(allv)
        if full in ("os.path.dirname", "posixpath.dirname"):
            return Val(u.taint, tuple(p for p in (_norm(posixpath.dirname(x) or ".") for x in argv[0].paths) if p)
                       if argv else (), u.text)
        if full in ("os.listdir", "os.walk", "os.scandir", "glob.glob", "glob.iglob"):
            return Val(u.taint, (), u.text)
        if full in ("io.open", "codecs.open"):
            return Val(u.taint, (), u.text | (argv[0].taint if argv else frozenset()))
        return u

    def targets_of(self, label: str, vals) -> list:
        """The tree files a command or path value runs; one unresolved target when none is found."""
        out = []
        for v in vals:
            for p in v.paths:
                for tok in ([p] + p.split()):
                    f = self.m.index.file_of_path(tok)
                    if f and Target(label, f) not in out:
                        out.append(Target(label, f))
        return out or [Target(label, None)]

    def module_targets(self, label: str, vals) -> list:
        out = []
        for v in vals:
            for p in v.paths:
                f = self.m.index.resolve_module(self.m.here, p, 0)
                if f:
                    out.append(Target(label, f))
        return out or [Target(label, None)]


# ---------------------------------------------------------------- the tests of a file


def _tests(mod: ast.Module):
    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test") \
                and not _is_fixture(node):
            yield node.name, node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    yield f"{node.name}.{sub.name}", sub


def _conftests(index: Index, rel: str) -> list[Module]:
    out, d = [], posixpath.dirname(rel)
    while True:
        c = _norm(posixpath.join(d, "conftest.py")) if d else "conftest.py"
        if c in index.fileset:
            m = index.module(c)
            if m is not None:
                out.append(m)
        if not d:
            return out
        d = posixpath.dirname(d)


def _param_values(module: Module, fn) -> dict:
    """Doc taint and paths each parametrize argument may carry."""
    out: dict[str, Val] = {}
    ctx = Ctx(module, Env(module.env), Result())
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "parametrize"):
            continue
        if len(d.args) < 2 or not isinstance(d.args[0], ast.Constant) or not isinstance(d.args[0].value, str):
            continue
        names = [x.strip() for x in d.args[0].value.split(",") if x.strip()]
        vals = d.args[1]
        if isinstance(vals, (ast.List, ast.Tuple)) and len(names) > 1:
            cols = [[] for _ in names]
            for row in vals.elts:
                if isinstance(row, (ast.Tuple, ast.List)) and len(row.elts) == len(names):
                    for i, e in enumerate(row.elts):
                        cols[i].append(ctx.expr(e))
                else:
                    v = ctx.expr(row)
                    for c in cols:
                        c.append(Val(v.taint, (), v.text))
            for nm, col in zip(names, cols):
                out[nm] = Val(frozenset().union(*(v.taint for v in col)), tuple(p for v in col for p in v.paths), _text(*col))
        else:
            v = ctx.expr(vals)
            for nm in names:
                out[nm] = Val(v.taint, v.paths if len(names) == 1 else (), v.text)
    return out


def analyze_test(module: Module, conftests: list, fn) -> Result:
    params = _param_values(module, fn)
    args, res = {}, Result()
    for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
        name = a.arg
        if name in params:
            args[name] = params[name]
            continue
        if name in ("self", "cls") or name in BUILTIN_FIXTURES:
            continue
        for m in [module] + conftests:
            fx = m.fixtures.get(name)
            if fx is not None:
                # a fixture carries values (doc text among them) and its assertions into the test;
                # the code it runs is set-up, not a consumer the test runs
                sub = m.call_helper(fx.name, _fixture_args(m, conftests, fx))
                res.asserts.extend(sub.asserts)
                args[name] = sub.ret
                break
    body = run_function(module, fn, args)
    res.asserts.extend(body.asserts)
    if body.code:
        res.code = True
        res.targets.extend(t for t in body.targets if t not in res.targets)
    return res


def _fixture_args(module: Module, conftests: list, fx, depth: int = 0) -> dict:
    """The values of the fixtures a fixture itself requests (their taint and paths)."""
    out = {}
    for d in fx.decorator_list:
        if isinstance(d, ast.Call):
            for k in d.keywords:
                if k.arg == "params":
                    out["request"] = Ctx(module, Env(module.env), Result()).expr(k.value)
    if depth > 4:
        return out
    for a in fx.args.args:
        for m in [module] + conftests:
            sub = m.fixtures.get(a.arg)
            if sub is not None and sub is not fx:
                out[a.arg] = m.call_helper(sub.name, _fixture_args(m, conftests, sub, depth + 1)).ret
                break
    return out


def judge(index: Index, module: Module, conftests: list, name: str, fn) -> str | None:
    """The finding message for one test, or None."""
    res = analyze_test(module, conftests, fn)
    if not res.asserts or not all(t for _, t in res.asserts):
        return None
    docs = sorted(frozenset().union(*(t for _, t in res.asserts)))
    plain = [d for d in docs if "*" not in posixpath.basename(d)] or docs
    shown = ", ".join(plain[:4]) + (" ..." if len(plain) > 4 else "")
    if not res.code:
        return f"{name} asserts only text presence in {shown} and runs no code"
    resolved = [t for t in res.targets if t.file]
    unresolved = [t for t in res.targets if not t.file]
    missing = [d for d in plain if not any(index.names(t.file, d) for t in resolved)]
    if not missing:
        return None
    if unresolved:
        what = ", ".join(sorted({t.label for t in unresolved}))
        return (f"{name} asserts only text presence in {shown}; the code it runs ({what}) cannot be resolved "
                f"to a file, so no consumer of {', '.join(missing[:3])} is shown (fails closed)")
    ran = ", ".join(sorted({t.file for t in resolved})[:4]) or "no file"
    return (f"{name} asserts only text presence in {shown}; the code it runs ({ran}) does not name "
            f"{', '.join(missing[:3])}")


def check_prose_only(tree: Tree) -> list[Finding]:
    enabled = gc.isenabled()
    gc.disable()                # the parse allocates millions of nodes; collection cycles only cost time
    try:
        return _check(tree)
    finally:
        if enabled:
            gc.enable()


def _check(tree: Tree) -> list[Finding]:
    index = Index(tree)
    out = []
    for rel in index.files:
        if not _TEST_FILE.search(rel):
            continue
        mod = index.module(rel)
        if mod is None:
            continue
        conftests = _conftests(index, rel)
        if not (mod.reaches_docs() or any(c.reaches_docs() for c in conftests)):
            continue
        for name, fn in _tests(mod.ast):
            msg = judge(index, mod, conftests, name, fn)
            if msg:
                out.append(Finding(CHECK, rel, fn.lineno, msg))
    return out
