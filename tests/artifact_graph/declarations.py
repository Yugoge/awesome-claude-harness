"""Declarations the check reads (row 19): canonical todo steps, the roster,
the command files, the schemas' ids and enums, settings.json's hook
registrations and env, and tool-policy allow prefixes.

The todo modules are evaluated by a small interpreter over their ast (literal
lists, tuples, dicts, f-strings, module constants, local helper calls, list
comprehensions, `x if cond else y` taken both ways, `from dev import
get_todos`); nothing is executed.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from . import mdscan


class _Unsupported(Exception):
    pass


class TodoEval:
    def __init__(self, tree: ast.Module, loader, path: str = "", text: str = ""):
        self.tree = tree
        self.loader = loader
        self.path = path
        self.text = text
        self.consts: dict[str, ast.AST] = {}
        self.funcs: dict[str, ast.FunctionDef] = {}
        self.imports: dict[str, tuple] = {}
        for s in tree.body:
            if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                self.consts[s.targets[0].id] = s.value
            elif isinstance(s, ast.FunctionDef):
                self.funcs[s.name] = s
            elif isinstance(s, ast.ImportFrom) and s.module:
                for a in s.names:
                    self.imports[a.asname or a.name] = (s.module, a.name)

    def variants(self, fname: str = "get_todos") -> tuple[list[list], "TodoEval"]:
        """The step lists the module yields, and the module that defines them."""
        if fname in self.funcs:
            return self.call(self.funcs[fname], [], {}), self
        if fname in self.imports:
            mod, name = self.imports[fname]
            other = self.loader(mod)
            if other is None:
                raise _Unsupported(f"import {mod}")
            return other.variants(name)
        # a module that prints its list: print(json.dumps(NAME, ...))
        for s in self.tree.body:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and getattr(s.value.func, "id", "") == "print":
                for a in s.value.args:
                    if isinstance(a, ast.Call) and getattr(a.func, "attr", "") == "dumps" and a.args:
                        return self.ev(a.args[0], {}), self
        raise _Unsupported("no get_todos")

    def call(self, fn: ast.FunctionDef, args: list, kw: dict) -> list:
        scope = {}
        params = [a.arg for a in fn.args.args]
        for p, v in zip(params, args):
            scope[p] = v
        scope.update(kw)
        r = self.run(fn.body, scope)
        return [None] if r is None else r

    def run(self, body: list, scope: dict) -> list | None:
        """Each variant the body may return (a list of python values); None
        when the body ends without a return."""
        for s in body:
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                continue
            if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                vs = self.ev(s.value, scope)
                scope[s.targets[0].id] = vs[0]
                if len(vs) > 1:
                    out = []
                    for v in vs:
                        sc = dict(scope)
                        sc[s.targets[0].id] = v
                        out += self.run(body[body.index(s) + 1:], sc) or [None]
                    return out
                continue
            if isinstance(s, ast.If):
                test = s.test
                if isinstance(test, ast.Name) and test.id in scope:
                    branch = s.body if scope[test.id] else s.orelse
                    r = self.run(branch, scope) if branch else None
                    if r is not None:
                        return r
                    continue
                raise _Unsupported("if")
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                f = s.value.func
                if isinstance(f, ast.Attribute) and f.attr == "update" and isinstance(f.value, ast.Name):
                    target = scope.get(f.value.id)
                    arg = self.ev(s.value.args[0], scope)[0]
                    if isinstance(target, dict) and isinstance(arg, dict):
                        target.update(arg)
                        continue
                raise _Unsupported("call stmt")
            if isinstance(s, ast.Return):
                return self.ev(s.value, scope)
            if isinstance(s, (ast.Import, ast.ImportFrom)):
                continue
            raise _Unsupported(type(s).__name__)
        return None

    def ev(self, n, scope: dict) -> list:
        if isinstance(n, ast.Constant):
            return [n.value]
        if isinstance(n, ast.Name):
            if n.id in scope:
                return [scope[n.id]]
            if n.id in self.consts:
                return self.ev(self.consts[n.id], {})
            raise _Unsupported(f"name {n.id}")
        if isinstance(n, (ast.List, ast.Tuple)):
            items = []
            for e in n.elts:
                v = self.ev(e, scope)
                items.append(v[0])
            return [list(items) if isinstance(n, ast.List) else tuple(items)]
        if isinstance(n, ast.Dict):
            d = {}
            for k, v in zip(n.keys, n.values):
                d[self.ev(k, scope)[0]] = self.ev(v, scope)[0]
            return [d]
        if isinstance(n, ast.JoinedStr):
            out = ""
            for p in n.values:
                if isinstance(p, ast.Constant):
                    out += str(p.value)
                else:
                    out += str(self.ev(p.value, scope)[0])
            return [out]
        if isinstance(n, ast.IfExp):
            return self.ev(n.body, scope) + self.ev(n.orelse, scope)
        if isinstance(n, ast.ListComp) and len(n.generators) == 1:
            gen = n.generators[0]
            results = []
            for it in self.ev(gen.iter, scope):
                items = []
                for elem in it:
                    sc = dict(scope)
                    self._bind(gen.target, elem, sc)
                    items.append(self.ev(n.elt, sc)[0])
                results.append(items)
            return results
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self.funcs:
            args = [self.ev(a, scope)[0] for a in n.args]
            kw = {k.arg: self.ev(k.value, scope)[0] for k in n.keywords}
            return self.call(self.funcs[n.func.id], args, kw)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a = self.ev(n.left, scope)[0]
            b = self.ev(n.right, scope)[0]
            return [a + b]
        raise _Unsupported(type(n).__name__)

    def _bind(self, target, val, scope) -> None:
        if isinstance(target, ast.Name):
            scope[target.id] = val
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t, v in zip(target.elts, val):
                self._bind(t, v, scope)
        else:
            raise _Unsupported("target")


def todo_steps(root: Path, files: list[str]) -> list[dict]:
    out: list[dict] = []
    todo_files = sorted(f for f in files if re.match(r"^scripts/todo/[^/]+\.py$", f))
    cache: dict = {}

    def load(mod: str):
        path = f"scripts/todo/{mod.split('.')[-1]}.py"
        if path not in todo_files:
            return None
        if path not in cache:
            try:
                text = (root / path).read_text(encoding="utf-8")
                cache[path] = TodoEval(ast.parse(text), load, path, text)
            except (SyntaxError, OSError):
                cache[path] = None
        return cache[path]

    for path in todo_files:
        command = path.rsplit("/", 1)[-1][:-3]
        ev = load(command)
        if ev is None:
            out.append({"kind": "declaration", "type": "todo_unread", "command": command,
                        "site": f"{path}:1", "reason": "syntax"})
            continue
        try:
            variants, definer = ev.variants()
        except (_Unsupported, KeyError, IndexError, TypeError, RecursionError) as exc:
            out.append({"kind": "declaration", "type": "todo_unread", "command": command,
                        "site": f"{path}:1", "reason": str(exc)[:80]})
            continue
        text = definer.text
        for vi, steps in enumerate(variants):
            if not isinstance(steps, list):
                continue
            for si, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                content = str(step.get("content", ""))
                call = step.get("subagent_call")
                agent = call.get("subagent_type") or call.get("agent") if isinstance(call, dict) else None
                out.append({
                    "kind": "declaration", "type": "todo_step", "command": command,
                    "variant": vi, "index": si + 1, "step": content,
                    "subagent_call": agent,
                    "site": f"{definer.path}:{_line_of_text(text, content, step)}",
                })
    return out


def _line_of_text(text: str, content: str, step: dict) -> int:
    m = re.match(r"Step (\S+): (.*)$", content)
    needles = [content]
    if m:
        needles += [f'"{m.group(2)}"', m.group(2)]
    for nd in needles:
        k = text.find(nd)
        if k >= 0:
            return text.count("\n", 0, k) + 1
    return 1


def roster(root: Path, files: list[str]) -> list[dict]:
    out = []
    for f in sorted(files):
        if re.match(r"^agents/[^/]+\.md$", f):
            text = (root / f).read_text(encoding="utf-8", errors="replace")
            if mdscan.front_matter(text) is not None:
                out.append({"kind": "declaration", "type": "roster_entry", "name": f.rsplit("/", 1)[-1][:-3],
                            "site": f"{f}:1"})
    return out


def command_files(root: Path, files: list[str]) -> list[dict]:
    out = []
    for f in sorted(files):
        if re.match(r"^commands/[^/]+\.md$", f):
            text = (root / f).read_text(encoding="utf-8", errors="replace")
            if mdscan.front_matter(text) is not None:
                out.append({"kind": "declaration", "type": "command", "name": f.rsplit("/", 1)[-1][:-3],
                            "site": f"{f}:1"})
    return out


def schemas(root: Path, files: list[str]) -> list[dict]:
    out = []
    reg_ids: dict[str, str] = {}
    if "schemas/registry.json" in files:
        try:
            reg = json.loads((root / "schemas/registry.json").read_text(encoding="utf-8"))
            for k, v in (reg.get("schemas") or {}).items():
                if isinstance(v, str):
                    reg_ids["schemas/" + v] = k
        except ValueError:
            pass
    for f in sorted(files):
        if not re.match(r"^schemas/[^/]+\.json$", f) or f == "schemas/registry.json":
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        try:
            doc = json.loads(text)
        except ValueError:
            out.append({"kind": "declaration", "type": "schema_unread", "site": f"{f}:1"})
            continue
        sid = None
        if isinstance(doc, dict) and isinstance(doc.get("$id"), str):
            sid = doc["$id"]
            sid = sid.rsplit("/", 1)[-1]
            if sid.endswith(".json"):
                sid = sid[:-5]
        sid = reg_ids.get(f, sid) or f.rsplit("/", 1)[-1][:-5]
        out.append({"kind": "declaration", "type": "schema", "id": sid, "site": f"{f}:1",
                    "registered": f in reg_ids})
        enum_lines = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(r'"enum"\s*:', text)]
        found: list = []
        _walk_enums(doc, "", found)
        for i, (ptr, vals) in enumerate(found):
            line = enum_lines[i] if i < len(enum_lines) else 1
            out.append({"kind": "declaration", "type": "schema_enum", "schema": sid, "pointer": ptr,
                        "values": vals, "site": f"{f}:{line}"})
    return out


def _walk_enums(node, ptr: str, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "enum" and isinstance(v, list):
                out.append((ptr + "/enum", v))
            else:
                _walk_enums(v, ptr + "/" + str(k).replace("~", "~0").replace("/", "~1"), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_enums(v, f"{ptr}/{i}", out)


def settings_hooks(root: Path, text: str) -> tuple[list[dict], dict]:
    """[(event, matcher, command, timeout, line)] and the env object."""
    try:
        doc = json.loads(text)
    except ValueError:
        return [], {}
    regs = []
    pos = 0
    for event, groups in (doc.get("hooks") or {}).items():
        for g in groups or []:
            for h in g.get("hooks") or []:
                cmd = h.get("command")
                if not isinstance(cmd, str):
                    continue
                needle = json.dumps(cmd)
                k = text.find(needle, pos)
                if k < 0:
                    k = text.find(needle)
                else:
                    pos = k + 1
                line = text.count("\n", 0, k) + 1 if k >= 0 else 1
                regs.append({"event": event, "matcher": g.get("matcher"), "command": cmd,
                             "timeout": h.get("timeout"), "line": line})
    env = doc.get("env") if isinstance(doc.get("env"), dict) else {}
    return regs, env


def policy_prefixes(root: Path, files: list[str]) -> list[dict]:
    out = []
    for f in sorted(files):
        if not re.match(r"^policies/tool-policy[^/]*\.json$", f):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        for role, spec in (doc.get("roles") or {}).items():
            if not isinstance(spec, dict):
                continue
            for key, vals in spec.items():
                if not (key.startswith("allowed") and "prefix" in key and isinstance(vals, list)):
                    continue
                for v in vals:
                    if not isinstance(v, str) or v.endswith("/") or v.endswith("*"):
                        continue
                    needle = json.dumps(v)
                    k = text.find(needle)
                    line = text.count("\n", 0, k) + 1 if k >= 0 else 1
                    out.append({"kind": "rule7", "class": "policy_file_prefix", "component": f,
                                "site": f"{f}:{line}", "role": role, "key": key, "prefix": v})
    return out
