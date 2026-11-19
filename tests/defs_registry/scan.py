"""Enumerate the literal definitions of hooks/ and scripts/: every table of two or more string
members a decision is written against, in each of the shapes the harness writes them.

A definition is (file, line, kind, name, members). `name` is the definition's scope-qualified
name, the part of its identity that survives a move to another line or file:
  py-table   NAME = ("a", "b") / frozenset({...}) / "a b".split()  -> <scope>.NAME
             (also class attributes, annotated assignments and a dict value: NAME[key])
  py-in      x in ("a", "b")  /  x.startswith(("a", "b"))          -> <scope>:in
  py-eq      x == "a" or x == "b"                                   -> <scope>:eq
  py-regex   an alternation (a|b|c) inside a string passed to re.*, or assigned to a name the
             file passes to re.*; one definition per group      -> <scope>:re  (or <scope>.NAME:re)
  sh-case    one case arm a|b|c)                                    -> <function>:case
             (not an arm of `case "$1"` whose words are all options: that is the script's
             own command line, like argparse in Python, not a fact about another program)
  sh-array   NAME=(a b c)                                           -> <function>.NAME
  sh-for     for x in a b c                                         -> <function>:for
  sh-regex   an alternation in a [[ =~ ]] operand or a grep -E / sed -E pattern -> <function>:re
<scope> is the dotted class/function path, "<module>" at module level; in shell, the last
function defined above the line, "<script>" before the first.

Not seen: a fact written as code (a function, a chain of startswith tests, a loop), tables
built at run time ("|".join(...), set unions), dict keys, JSON and settings files, Python
inside a shell here-document, and a regex alternation unless every alternative is plain
text (a nested group or a class such as [a-z] keeps the alternation out; `x?` is expanded).
"""
from __future__ import annotations

import ast
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

TESTY = re.compile(r"(^|/)(tests?|fixtures|__pycache__)/|(^|/)test_[^/]*$|_test\.py$|(^|/)conftest\.py$")
RE_FUNCS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
WRAPPERS = {"frozenset", "set", "tuple", "list", "sorted"}


@dataclass(frozen=True)
class Definition:
    file: str
    line: int
    kind: str
    name: str
    members: frozenset

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


# ------------------------------------------------------------------ files
def source_files(tree: Path) -> list[tuple[str, str, str]]:
    """(path, language, text) for every tracked non-test file under hooks/ and scripts/."""
    out = subprocess.run(["git", "-C", str(tree), "ls-files", "-z", "--", "hooks", "scripts"],
                         capture_output=True, text=True, check=True).stdout
    files = []
    for rel in sorted(p for p in out.split("\0") if p and not TESTY.search(p)):
        try:
            text = (tree / rel).read_bytes().decode("utf-8", "replace")
        except OSError:          # tracked but deleted in the work tree
            continue
        first = text.split("\n", 1)[0]
        if rel.endswith(".py") or (first.startswith("#!") and "python" in first):
            files.append((rel, "py", text))
        elif rel.endswith(".sh") or (first.startswith("#!") and re.search(r"\b(ba|da|z)?sh\b", first)):
            files.append((rel, "sh", text))
    return files


# ------------------------------------------------------------------ regular expressions
GROUP_PREFIX = re.compile(r"^\?(?:[:=!>]|<[=!]|P<\w+>|[aiLmsux-]+:)")
META = re.compile(r"(?<!\\)[.^$*+?{}\[\]()|]|\\[a-zA-Z0-9]")


def _alternations(pat: str) -> list[list[str]]:
    """The alternatives of the top level and of every group of `pat`, as source text."""
    res: list[list[str]] = []

    def parse(i: int, depth: int) -> int:
        alts, cur, n = [], [], len(pat)
        while i < n:
            c = pat[i]
            if c == "\\" and i + 1 < n:
                cur.append(pat[i:i + 2]); i += 2; continue
            if c == "[":
                j = i + 1
                if j < n and pat[j] == "^":
                    j += 1
                if j < n and pat[j] == "]":
                    j += 1
                while j < n and pat[j] != "]":
                    j += 2 if pat[j] == "\\" else 1
                cur.append(pat[i:j + 1]); i = j + 1; continue
            if c == "(":
                j = parse(i + 1, depth + 1)
                cur.append(pat[i:j]); i = j; continue
            if c == ")" and depth > 0:
                alts.append("".join(cur))
                if len(alts) > 1:
                    res.append(alts)
                return i + 1
            if c == "|":
                alts.append("".join(cur)); cur = []; i += 1; continue
            cur.append(c); i += 1
        alts.append("".join(cur))
        if len(alts) > 1:
            res.append(alts)
        return i

    try:
        parse(0, 0)
    except RecursionError:
        pass
    return res


OPT_CHAR = re.compile(r"(\\.|[^\\])\?")


def _literal_alt(a: str) -> list[str] | None:
    """The literal texts an alternative matches, or None when it is not a plain literal.
    Anchors and word boundaries at its ends are dropped, escapes undone, and a single
    optional character expanded (`ya?ml` is yaml and yml; at most two per alternative)."""
    a = GROUP_PREFIX.sub("", a)
    a = re.sub(r"^(?:\\b|\^|\\A|\\s\+|\\s\*)+", "", a)
    a = re.sub(r"(?:\\b|\$|\\Z|\\s\+|\\s\*)+$", "", a)
    forms = [a]
    for _ in range(2):
        m = OPT_CHAR.search(forms[0])
        if not m or m.group(1) in "()[]{}":
            break
        forms = [f[:m.start()] + x + f[m.end():] for f in forms for x in (m.group(1), "")]
    if not a or any(not f or META.search(f) for f in forms):
        return None
    return [re.sub(r"\\(.)", r"\1", f) for f in forms]


def regex_tables(pat: str) -> list[frozenset]:
    """One member set per alternation of `pat` whose alternatives are all plain literals."""
    out = []
    for alts in _alternations(pat):
        lits = [_literal_alt(a) for a in alts]
        if all(x is not None for x in lits):
            members = frozenset(m for x in lits for m in x)
            if len(members) >= 2:
                out.append(members)
    return out


# ------------------------------------------------------------------ python
def _strs(node) -> list[str] | None:
    """The members of a literal string collection (unwrapping frozenset(...) & co. and
    "a b".split()), or None when the node is not one."""
    if isinstance(node, ast.Call) and not node.keywords:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in WRAPPERS and len(node.args) == 1:
            return _strs(node.args[0])
        if isinstance(fn, ast.Attribute) and fn.attr == "split" and not node.args \
                and isinstance(fn.value, ast.Constant) and isinstance(fn.value.value, str):
            return fn.value.value.split()
        return None
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


def _inline_strs(node) -> list[str] | None:
    """A literal tested inline: as _strs, but other elements (None, a named constant) are
    left out, as the first inventory did."""
    m = _strs(node)
    if m is None and isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        m = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return m or None


def _target(t) -> str:
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    return "<expr>"


class _Py(ast.NodeVisitor):
    def __init__(self, rel: str, out: list):
        self.rel, self.out, self.scope = rel, out, []
        self.re_names: set[str] = set()

    def add(self, kind, line, name, members):
        m = frozenset(members)
        if len(m) >= 2:
            self.out.append(Definition(self.rel, line, kind, name, m))

    def where(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _scoped(self, n):
        self.scope.append(n.name)
        self.generic_visit(n)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def _assigned(self, target, value, line):
        name = f"{self.where()}.{_target(target)}"
        m = _strs(value)
        if m is not None:
            self.add("py-table", line, name, m)
        elif isinstance(value, ast.Dict):
            for k, v in zip(value.keys, value.values):
                mv = _strs(v)
                if mv is not None and isinstance(k, ast.Constant) and isinstance(k.value, str):
                    self.add("py-table", v.lineno, f"{name}[{k.value}]", mv)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str) \
                and _target(target) in self.re_names:
            for s in regex_tables(value.value):
                self.add("py-regex", line, f"{name}:re", s)

    def visit_Assign(self, n):
        for t in n.targets:
            self._assigned(t, n.value, n.lineno)
        self.generic_visit(n)

    def visit_AnnAssign(self, n):
        if n.value is not None:
            self._assigned(n.target, n.value, n.lineno)
        self.generic_visit(n)

    def visit_Compare(self, n):
        for op, comp in zip(n.ops, n.comparators):
            if isinstance(op, (ast.In, ast.NotIn)):
                m = _inline_strs(comp)
                if m is not None:
                    self.add("py-in", n.lineno, f"{self.where()}:in", m)
        self.generic_visit(n)

    def visit_BoolOp(self, n):
        groups: dict = {}
        for v in n.values:
            if isinstance(v, ast.Compare) and len(v.ops) == 1 and isinstance(v.ops[0], (ast.Eq, ast.NotEq)):
                a, b = v.left, v.comparators[0]
                for subj, lit in ((a, b), (b, a)):
                    if isinstance(lit, ast.Constant) and isinstance(lit.value, str) \
                            and not isinstance(subj, ast.Constant):
                        groups.setdefault((ast.dump(subj), type(v.ops[0])), []).append(lit.value)
        for lits in groups.values():
            self.add("py-eq", n.lineno, f"{self.where()}:eq", lits)
        self.generic_visit(n)

    def visit_Call(self, n):
        fn = n.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("startswith", "endswith") and n.args:
            m = _strs(n.args[0])
            if m is not None:
                self.add("py-in", n.lineno, f"{self.where()}:in", m)
        if isinstance(fn, ast.Attribute) and fn.attr in RE_FUNCS and isinstance(fn.value, ast.Name) \
                and fn.value.id in ("re", "regex") and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                for s in regex_tables(a.value):
                    self.add("py-regex", n.lineno, f"{self.where()}:re", s)
        self.generic_visit(n)


def _re_names(tree) -> set[str]:
    """Names this module passes as the pattern of a re.* call."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in RE_FUNCS \
                and isinstance(n.func.value, ast.Name) and n.func.value.id in ("re", "regex") and n.args:
            a = n.args[0]
            if isinstance(a, (ast.Name, ast.Attribute)):
                names.add(_target(a))
    return names


def python_defs(rel: str, text: str) -> tuple[list[Definition], str | None]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"{rel}: {exc.msg} (line {exc.lineno})"
    out: list[Definition] = []
    v = _Py(rel, out)
    v.re_names = _re_names(tree)
    v.visit(tree)
    return out, None


# ------------------------------------------------------------------ shell
SH_FUNC = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w:.-]*)\s*\(\)\s*\{?")
SH_ARRAY = re.compile(r"^\s*(?:(?:local|declare|readonly|typeset)\s+(?:-\w+\s+)*)?([A-Za-z_]\w*)=\((.*)$")
SH_FOR = re.compile(r"^\s*for\s+\w+\s+in\s+(.+?)\s*(?:;\s*do\b.*|$)")
SH_ARM = re.compile(r"^\s*\(?\s*((?:[^\s|()]+\s*\|\s*)+[^\s|()]+)\s*\)")
SH_REGEX = re.compile(r"=~\s*(\"[^\"]*\"|'[^']*'|\S+)|\b(?:grep|sed)\s+(?:-\w*\s+)*-\w*E\w*\s+(?:-\w+\s+)*(\"[^\"]*\"|'[^']*')"
                      r"|\begrep\s+(?:-\w+\s+)*(\"[^\"]*\"|'[^']*')")
OWN_ARG = re.compile(r"^\"?\$\{?1(:-[^}]*)?\}?\"?$")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")


def _words(s: str) -> list[str] | None:
    try:
        w = shlex.split(s, comments=True)
    except ValueError:
        return None
    if not w or any("$" in x or "`" in x for x in w):
        return None
    return w


def shell_defs(rel: str, text: str) -> list[Definition]:
    out: list[Definition] = []
    lines = text.split("\n")
    func, cases, heredoc, i = "<script>", [], None, 0

    def add(kind, line, name, members):
        m = frozenset(members)
        if len(m) >= 2:
            out.append(Definition(rel, line, kind, name, m))

    while i < len(lines):
        raw, ln = lines[i], i + 1
        i += 1
        if heredoc:
            if raw.strip() == heredoc:
                heredoc = None
            continue
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        hd = HEREDOC.search(raw)
        if hd and not re.search(r"<<<", raw):
            heredoc = hd.group(2)
        fm = SH_FUNC.match(raw)
        if fm and not s.startswith(("if ", "while ", "for ")):
            func = fm.group(1)
        cm = re.match(r"^case\s+(.*?)\s+in\b", s)
        if cm:
            cases.append(cm.group(1))
        if re.search(r"(^|[;\s])esac\b", s) and cases:
            cases.pop()
        if cases and not cm:
            am = SH_ARM.match(raw)
            if am:
                w = [x.strip().strip("'\"") for x in am.group(1).split("|")]
                # `case "$1" in -h|--help)`: the script's own options, its interface
                # (as argparse is in Python), not a fact about another program.
                if not (OWN_ARG.match(cases[-1]) and all(x.startswith("-") for x in w)):
                    add("sh-case", ln, f"{func}:case", w)
        am = SH_ARRAY.match(raw)
        if am:
            body, start = am.group(2), ln
            while ")" not in re.sub(r"\"[^\"]*\"|'[^']*'", "", body.split("#")[0]) and i < len(lines):
                body += "\n" + lines[i]
                i += 1
            body = body[:body.rfind(")")] if ")" in body else body
            w = _words(body)
            if w is not None:
                add("sh-array", start, f"{func}.{am.group(1)}", w)
        fm2 = SH_FOR.match(raw)
        if fm2:
            w = _words(fm2.group(1))
            if w is not None:
                add("sh-for", ln, f"{func}:for", w)
        for m in SH_REGEX.finditer(raw):
            pat = next(g for g in m.groups() if g is not None)
            if pat[:1] in "\"'":
                pat = pat[1:-1]
            for st in regex_tables(pat):
                add("sh-regex", ln, f"{func}:re", st)
    return out


def scan(tree: Path) -> tuple[list[Definition], list[str]]:
    """Every definition of the tree, deduplicated on (file, line, members), and the files
    that could not be parsed."""
    defs, errors, seen = [], [], set()
    for rel, lang, text in source_files(tree):
        if lang == "py":
            found, err = python_defs(rel, text)
            if err:
                errors.append(err)
        else:
            found = shell_defs(rel, text)
        for d in found:
            key = (d.file, d.line, d.members)
            if key not in seen:
                seen.add(key)
                defs.append(d)
    return defs, errors
