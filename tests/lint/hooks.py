"""The two hook checks: output that never reaches the model, and state files with two writers.

What reaches the model (the CLI's hook contract): the stderr of an exit 2; a JSON object on
stdout that carries `decision`, `permissionDecision` or `additionalContext`; and, on
SessionStart and UserPromptSubmit only, plain stdout on exit 0. Everything else a hook
prints -- stderr on exit 0 or 1, plain stdout on any other event -- goes to the transcript
at most, so a hook that prints and has none of those channels talks to no one.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from .tree import Finding, Tree

CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit"}
JSON_KEYS = ("decision", "permissionDecision", "additionalContext")
_JSON_KEY_RE = re.compile(r"""\\?["'](?:%s)\\?["']""" % "|".join(JSON_KEYS))


@dataclass
class Facts:
    can_block: bool = False                     # some path exits 2
    json_channel: bool = False                  # emits a model-visible JSON field
    stderr_lines: list = field(default_factory=list)
    stdout_lines: list = field(default_factory=list)


# ---------------------------------------------------------------- Python hooks

def _const_names(tree: ast.AST) -> dict[str, list]:
    """name -> every value assigned to it (ast nodes), across all scopes."""
    out: dict[str, list] = {}
    for n in ast.walk(tree):
        targets, value = [], None
        if isinstance(n, ast.Assign):
            targets, value = n.targets, n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            targets, value = [n.target], n.value
        for t in targets:
            if isinstance(t, ast.Name):
                out.setdefault(t.id, []).append(value)
    return out


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _is_stream(node, stream: str) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == stream and isinstance(node.value, ast.Name) \
        and node.value.id == "sys"


def _is_exit(node) -> ast.AST | None:
    """The status expression of `sys.exit(x)`, `exit(x)`, `os._exit(x)` or `raise SystemExit(x)`."""
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and _call_name(node.exc) == "SystemExit":
        return node.exc.args[0] if node.exc.args else None
    if isinstance(node, ast.Call) and _call_name(node) in ("exit", "_exit", "SystemExit") and node.args:
        return node.args[0]
    return None


class _Statuses:
    """Whether an exit status expression of one module may be 2. A name or a local function
    is followed to what it is bound to or returns; a status that comes from anywhere else
    (another module, a child process) may be 2."""

    def __init__(self, mod: ast.AST):
        self.names = _const_names(mod)
        self.functions = {n.name: n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self._busy: set = set()

    def may_be_two(self, node) -> bool:
        if node is None or isinstance(node, ast.Constant):
            return node is not None and node.value == 2
        if isinstance(node, ast.IfExp):
            return self.may_be_two(node.body) or self.may_be_two(node.orelse)
        if isinstance(node, ast.Name):
            vals = self.names.get(node.id)
            if not vals:
                return True
            if ("name", node.id) in self._busy:
                return False
            self._busy.add(("name", node.id))
            try:
                return any(self.may_be_two(v) for v in vals)
            finally:
                self._busy.discard(("name", node.id))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.functions:
            fn = self.functions[node.func.id]
            if fn.name in self._busy:
                return False
            self._busy.add(fn.name)
            try:
                return any(self.may_be_two(r.value) for r in ast.walk(fn) if isinstance(r, ast.Return)
                           and r.value is not None)
            finally:
                self._busy.discard(fn.name)
        if isinstance(node, ast.Call) and _call_name(node) in ("int", "bool"):
            return True
        return not isinstance(node, (ast.JoinedStr, ast.List, ast.Dict, ast.Tuple))


def _main_guard_lines(mod: ast.AST) -> set:
    """Line numbers under `if __name__ == "__main__":`, which do not run on import."""
    out = set()
    for n in getattr(mod, "body", []):
        if isinstance(n, ast.If) and "__main__" in ast.dump(n.test):
            for sub in ast.walk(n):
                if hasattr(sub, "lineno"):
                    out.add(sub.lineno)
    return out


def _local_modules(tree: Tree, rel: str, mod: ast.AST) -> list[str]:
    """Tree-relative paths of the modules a hook imports from the harness itself."""
    here = os.path.dirname(rel)
    bases = [here, "hooks", "hooks/lib", "scripts", "scripts/lib"]
    out = []
    for n in ast.walk(mod):
        names = []
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            names = [base] if base else []
            names += [f"{base}.{a.name}" if base else a.name for a in n.names]
        for name in names:
            for b in bases:
                cand = os.path.normpath(os.path.join(b, *name.split("."))) + ".py"
                pkg = os.path.normpath(os.path.join(b, *name.split("."), "__init__.py"))
                for c in (cand, pkg):
                    if tree.exists(c) and c not in out:
                        out.append(c)
    return out


def _json_keys_in(mod: ast.AST) -> bool:
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and (n.value in JSON_KEYS or _JSON_KEY_RE.search(n.value)) for n in ast.walk(mod))


def python_facts(tree: Tree, rel: str) -> Facts:
    """The hook's own module decides; a module it imports from the harness adds a channel
    only by an explicit exit 2 outside its `__main__` block or a model-visible JSON key (the
    helper that emits a decision for it). Its prints count only outside except handlers:
    a diagnostic of a hook's own failure is not its message."""
    facts = Facts()
    try:
        mod = ast.parse(tree.read(rel))
    except (SyntaxError, ValueError, OSError):
        facts.can_block = True              # unreadable: assume it can, never report it
        return facts
    statuses = _Statuses(mod)
    parents = {c: p for p in ast.walk(mod) for c in ast.iter_child_nodes(p)}

    def in_handler(node) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.ExceptHandler):
                return True
        return False

    facts.json_channel = _json_keys_in(mod)
    for n in ast.walk(mod):
        status = _is_exit(n)
        if status is not None and not (isinstance(n, ast.Call) and isinstance(parents.get(n), ast.Raise)):
            facts.can_block |= statuses.may_be_two(status)
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if name == "print":
            dest = next((k.value for k in n.keywords if k.arg == "file"), None)
            if dest is None or _is_stream(dest, "stdout"):
                facts.stdout_lines.append(n.lineno)
            elif _is_stream(dest, "stderr") and not in_handler(n):
                facts.stderr_lines.append(n.lineno)
        elif name == "write" and isinstance(n.func, ast.Attribute):
            if _is_stream(n.func.value, "stderr") and not in_handler(n):
                facts.stderr_lines.append(n.lineno)
            elif _is_stream(n.func.value, "stdout"):
                facts.stdout_lines.append(n.lineno)
    for dep in _local_modules(tree, rel, mod):
        try:
            sub = ast.parse(tree.read(dep))
        except (SyntaxError, ValueError, OSError):
            continue
        guarded = _main_guard_lines(sub)
        sub_names = _const_names(sub)
        for n in ast.walk(sub):
            status = _is_exit(n)
            if status is not None and getattr(n, "lineno", 0) not in guarded:
                if isinstance(status, ast.Constant) and status.value == 2 or isinstance(status, ast.Name) and any(
                        isinstance(v, ast.Constant) and v.value == 2 for v in sub_names.get(status.id, [])):
                    facts.can_block = True
        facts.json_channel |= _json_keys_in(sub)
    return facts


# ---------------------------------------------------------------- shell hooks

_PRINT = re.compile(r"(?:^\s*|[;&|{()]\s*|\bthen\s+|\belse\s+|\bdo\s+)(echo|printf|cat\b(?=[^\n;|]*<<))\b")
_STMT_END = re.compile(r";|&&|\|\||\||\}")
_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_]\w*)\1")


def _shell_code(text: str) -> list[str]:
    """The shell text with comments, heredoc bodies and command substitutions blanked out,
    line for line: what is left is what the script itself runs and prints."""
    lines, out, end = text.split("\n"), [], None
    for line in lines:
        if end is not None:
            out.append("")
            if line.strip() == end:
                end = None
            continue
        if line.lstrip().startswith("#"):
            out.append("")
            continue
        m = _HEREDOC.search(line)
        if m:
            end = m.group(2)
        out.append(line)
    return _drop_substitutions("\n".join(out)).split("\n")


def _drop_substitutions(text: str) -> str:
    """`$( ... )` and backtick spans blanked (newlines kept), quotes and nesting respected."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("$(", i) or text[i] == "`":
            j = _subst_end(text, i)
            out.append("\n" * text.count("\n", i, j))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _subst_end(text: str, i: int) -> int:
    if text[i] == "`":
        j = text.find("`", i + 1)
        return len(text) if j < 0 else j + 1
    depth, j, n = 0, i + 1, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c in "'\"":
            k = text.find(c, j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _unquote(line: str) -> str:
    """The line with quoted text and ${...} expansions blanked, positions kept: a `}`, `;` or
    `>` inside them neither ends a statement nor redirects it."""
    out, i, n = list(line), 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"" or line.startswith("${", i):
            close = "}" if c == "$" else c
            j = line.find(close, i + (2 if c == "$" else 1))
            j = n - 1 if j < 0 else j
            for k in range(i + 1, j):
                out[k] = " "
            i = j + 1
            continue
        i += 1
    return "".join(out)


def shell_facts(tree: Tree, rel: str) -> Facts:
    facts = Facts()
    try:
        text = tree.read(rel)
    except OSError:
        facts.can_block = True
        return facts
    code = _shell_code(text)
    joined = "\n".join(code)
    to_stderr = bool(re.search(r"^\s*exec\s+(?:1)?>&2\s*(?:#.*)?$", joined, re.M))
    facts.can_block = bool(re.search(r"\bexit\s+2\b|\bexit\s+\"?\$|\bexec\s+(?:python3?|bash|sh)\b"
                                     r"|\breturn\s+2\b", joined))
    facts.json_channel = bool(_JSON_KEY_RE.search(joined))
    for n, line in enumerate(code, 1):
        line = _unquote(line)
        for m in _PRINT.finditer(line):
            rest = line[m.start(1):]
            end = _STMT_END.search(rest)
            stmt = rest[: end.start()] if end else rest
            if end and end.group(0) == "|":
                continue                    # piped into another command: not output
            if re.search(r"(?:1)?>&2|/dev/stderr", stmt) or (to_stderr and ">" not in stmt):
                facts.stderr_lines.append(n)
            elif ">" not in stmt:
                facts.stdout_lines.append(n)
    return facts


def facts_of(tree: Tree, rel: str) -> Facts:
    return python_facts(tree, rel) if rel.endswith(".py") else shell_facts(tree, rel)


def check_unreachable_output(tree: Tree) -> list[Finding]:
    out, seen = [], set()
    for reg in tree.registrations:
        if (reg.event, reg.path) in seen or not tree.exists(reg.path):
            continue
        seen.add((reg.event, reg.path))
        f = facts_of(tree, reg.path)
        context = reg.event in CONTEXT_EVENTS
        reaches = f.can_block or f.json_channel or (context and f.stdout_lines)
        said = f.stderr_lines + ([] if context else f.stdout_lines)
        if said and not reaches:
            where = "stderr" if f.stderr_lines else "stdout"
            out.append(Finding("unreachable-output", reg.path, min(said),
                               f"registered on {reg.event} ({reg.matcher}); it prints to {where} "
                               f"(lines {', '.join(map(str, sorted(set(said))[:8]))}) but never exits 2 and "
                               f"emits no {'/'.join(JSON_KEYS)} JSON, so the model never sees it"))
    return out


# ---------------------------------------------------------------- 6. two writers

# A state file: what the harness keeps for itself at run time, under the state directory,
# the session scratch, the harness home, the user's home or the project's .claude/.
STATE_ROOTS = ("<state>/", "<tmpdir>/", "<harness>/", "<home>/", "<proj>/.claude/", "/")

# Run in the tree under check, by its own artifact check: the static half's relations, joined
# into artifacts by check.derive, with rule (1)'s count of producers.
_DERIVE = r"""
import json, sys
from tests.artifact_graph import check as C
from tests.artifact_graph.static_half import derive
root = sys.argv[1]
m = C.derive(root, derive(root), [])
count = getattr(C, "_producing", None)
out = []
for key, a in sorted(m.artifacts.items()):
    producers = count(a, m.ctx) if count else a.producers()
    out.append({"key": key, "kind": a.kind, "producers": list(producers),
                "writers": sorted({(w.who, w.evidence) for w in a.writers})})
json.dump(out, sys.stdout)
"""


def state_writer_findings(artifacts: list[dict]) -> list[Finding]:
    """A finding for each state-file artifact with two or more producers."""
    out = []
    for a in artifacts:
        key, prods = a["key"], a["producers"]
        if a.get("kind", "file") != "file" or not key.startswith(STATE_ROOTS) or len(prods) < 2:
            continue
        evidence = {}
        for who, ev in sorted(a.get("writers", [])):
            evidence.setdefault(who, ev)
        path, _, line = evidence.get(prods[0], "").partition(":")
        line = line.split(":")[0]
        out.append(Finding("two-writers", path or key, int(line) if line.isdigit() else 0,
                           f"{key} has {len(prods)} writers: "
                           + "; ".join(f"{p} [{evidence.get(p, '?')}]" for p in prods)))
    return out


def derive_artifacts(tree: Tree) -> list[dict]:
    """The tree's artifacts as its own artifact check (tests/artifact_graph) derives them."""
    if not tree.exists("tests/artifact_graph/check.py"):
        raise LookupError("the artifact check (tests/artifact_graph), which derives every writer, is not in this tree")
    env = dict(os.environ, PYTHONPATH=str(tree.root), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-c", _DERIVE, str(tree.root)], cwd=str(tree.root), env=env,
                          capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise LookupError("the artifact check failed: " + proc.stderr.strip()[-600:])
    return json.loads(proc.stdout)


def check_two_writers(tree: Tree) -> list[Finding]:
    try:
        artifacts = derive_artifacts(tree)
    except LookupError as exc:
        return [Finding("two-writers", "tests/artifact_graph", 0, str(exc))]
    return state_writer_findings(artifacts)
