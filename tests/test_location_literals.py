"""Absolute system directories are named in one file: hooks/lib/locations.py.

A hook that decides by a location asks that file. This check holds the rest of hooks/ and
scripts/ to it with the method of the hardcode audit's inventory (2026-11-19): in every
tracked non-test Python file, each comparison of text against a literal (startswith and
endswith, == and !=, membership in a literal collection, a literal pattern handed to re) and
each literal table of two or more strings is read from the syntax tree, and one that names an
absolute system directory anywhere but the one file fails here, named by file and line.
On f199dfb1e the same method found 51 such comparisons and 19 such tables in 14 files.

What the method does not see: shell files (counted by the inventory, never parsed), a literal
passed as a plain argument, and a pattern built at run time. A literal pattern that spells a
name beginning like a system directory (the command /dev-overnight) reads as that directory;
such a pattern is built from the name instead.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ONE_FILE = "hooks/lib/locations.py"
TESTY = re.compile(r"(^|/)(tests?|fixtures|__pycache__)/|(^|/)test_[^/]*$|_test\.py$|(^|/)conftest\.py$")
ABSSYS = re.compile(r"^/(dev|tmp|var|root|home|Users|usr|bin|etc|opt|proc|sys|run|private|boot)(/|$)")
RX_ABSSYS = re.compile(r"(?<![\w.])/(dev|tmp|var|root|home|Users|usr|bin|etc|opt|proc|sys|run|private|boot)(/|\b)")
RE_FUNCS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
COLLECTIONS = (ast.Tuple, ast.List, ast.Set)


def _strings(node) -> list:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, COLLECTIONS):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _unwrap(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
            "frozenset", "set", "tuple", "list") and len(node.args) == 1 and not node.keywords:
        return node.args[0]
    return node


class _Sites(ast.NodeVisitor):
    """(line, kind, literal) of each comparison against a literal, and (line, name, members) of each
    literal table, as the inventory reads them."""

    def __init__(self):
        self.sites, self.tables = [], []

    def visit_Call(self, n):
        fn = n.func
        if isinstance(fn, ast.Attribute) and n.args:
            if fn.attr in ("startswith", "endswith"):
                self.sites += [(n.lineno, "prefix" if fn.attr == "startswith" else "suffix", s)
                               for s in _strings(n.args[0])]
            elif fn.attr in RE_FUNCS and isinstance(fn.value, ast.Name) and fn.value.id == "re":
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    self.sites.append((n.lineno, "regex", a.value))
        self.generic_visit(n)

    def visit_Compare(self, n):
        prev = n.left
        for op, comp in zip(n.ops, n.comparators):
            if isinstance(op, (ast.In, ast.NotIn)):
                inner = _unwrap(comp)
                members = _strings(inner) if isinstance(inner, COLLECTIONS) else []
                if members:
                    self.sites += [(n.lineno, "inline-set", s) for s in members]
                    if len(set(members)) >= 2:
                        self.tables.append((n.lineno, "<inline>", tuple(sorted(set(members)))))
                elif isinstance(prev, ast.Constant) and isinstance(prev.value, str):
                    self.sites.append((n.lineno, "substring", prev.value))
            elif isinstance(op, (ast.Eq, ast.NotEq)):
                self.sites += [(n.lineno, "equals", side.value) for side in (prev, comp)
                               if isinstance(side, ast.Constant) and isinstance(side.value, str)]
            prev = comp
        self.generic_visit(n)

    def _table(self, target, value, line):
        inner = _unwrap(value)
        if isinstance(inner, COLLECTIONS) and inner.elts and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in inner.elts):
            members = tuple(sorted({e.value for e in inner.elts}))
            if len(members) >= 2:
                name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "<expr>")
                self.tables.append((line, name, members))

    def visit_Assign(self, n):
        if n.targets:
            self._table(n.targets[0], n.value, n.lineno)
        self.generic_visit(n)

    def visit_AnnAssign(self, n):
        if n.value is not None:
            self._table(n.target, n.value, n.lineno)
        self.generic_visit(n)


def _names_system_directory(kind: str, literal: str) -> bool:
    if kind == "regex":
        return bool(RX_ABSSYS.search(literal.replace("\\/", "/").replace("\\.", ".")))
    return bool(ABSSYS.search(literal))


def scan(source: str) -> tuple:
    """(comparisons, tables) of ``source`` that name an absolute system directory."""
    visitor = _Sites()
    visitor.visit(ast.parse(source))
    return ([s for s in visitor.sites if _names_system_directory(s[1], s[2])],
            [t for t in visitor.tables if any(ABSSYS.search(m) for m in t[2])])


def _python_files() -> list:
    """The tracked non-test Python files of hooks/ and scripts/ (every file there when this tree is
    no git checkout), by extension or by interpreter line."""
    try:
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", "hooks", "scripts"],
                                capture_output=True, text=True, check=True, timeout=60).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        listed = []
    if not listed:
        listed = [os.path.relpath(os.path.join(d, f), ROOT) for top in ("hooks", "scripts")
                  for d, _dirs, files in os.walk(ROOT / top) for f in files]
    out = []
    for rel in sorted(listed):
        path = ROOT / rel
        if TESTY.search(rel) or not path.is_file():
            continue
        if not rel.endswith(".py"):
            try:
                first = path.open("rb").readline().decode("utf-8", "replace")
            except OSError:
                continue
            if not (first.startswith("#!") and "python" in first):
                continue
        out.append(rel)
    return out


def _findings() -> dict:
    found = {}
    for rel in _python_files():
        sites, tables = scan((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        if sites or tables:
            found[rel] = (sites, tables)
    return found


def test_system_directories_are_named_in_the_one_file_only():
    files = _python_files()
    assert len(files) > 200 and ONE_FILE in files, "the scan must read the harness's own sources"
    found = _findings()
    elsewhere = [f"{rel}:{line} [{kind}] {literal!r}" for rel, (sites, tables) in sorted(found.items())
                 if rel != ONE_FILE for line, kind, literal in sites + [(t[0], "table " + t[1], t[2]) for t in tables]]
    assert not elsewhere, (
        f"{len(elsewhere)} comparison(s) or table(s) name an absolute system directory outside {ONE_FILE}; "
        "ask hooks/lib/locations.py instead:\n" + "\n".join(elsewhere))
    # the positive control: the one file is where the method finds them
    sites, tables = found[ONE_FILE]
    assert tables and any("/tmp" in t[2] for t in tables), "the scan no longer sees the one file's own tables"


PLANTED = [
    ('ok = path.startswith("/dev/")', 1, 0),
    ('ok = path == "/tmp" or "/var/tmp" != path', 2, 0),
    ('ok = head in ("/bin", "/usr/bin")', 2, 1),
    ('ok = head not in frozenset({"/dev/null", "/dev/tty"})', 2, 1),
    ('ROOTS = ("/tmp", "/var/tmp")', 0, 1),
    ('ROOTS: tuple = frozenset(["/root", "/home"])', 0, 1),
    ('import re\nok = re.search(r"^/proc/[^/]+/fd", text)', 1, 0),
    ('import re\nRX = re.compile(r"(/bin/|/usr/bin/)?(bash|sh)")', 1, 0),
    # not a system directory, or not a decision the method reads
    ('ok = path.startswith("/docs/dev/")', 0, 0),
    ('ok = name == "dev" or path.endswith(".tmp")', 0, 0),
    ('ROOTS = ("docs", "dev", "specs")', 0, 0),
    ('ok = path.startswith(locations.FD_DIR) or path in locations.STD_SINKS', 0, 0),
    ('ok = path == locations.NULL_DEVICE', 0, 0),
]


@pytest.mark.parametrize("source,comparisons,tables", PLANTED)
def test_the_scan_sees_each_shape(source, comparisons, tables):
    sites, found_tables = scan(source)
    assert (len(sites), len(found_tables)) == (comparisons, tables), (sites, found_tables)
