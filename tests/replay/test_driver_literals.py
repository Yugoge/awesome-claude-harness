"""Every literal a replay driver looks for in a command or agent file exists in today's text.

The drivers find their steps by the text of commands/*.md and agents/*.md: a heading, an anchor sentence, the
start of an inline code. When a lane removes or rewords such a line, the driver raises TextNotFound only when its
replay runs, which nobody does locally. This test reads the drivers and the replay helpers statically (no replay),
takes every string literal handed to a text lookup, and requires it in today's text (whitespace folded), unless
the same file declares it as text of an older version with a comment line `# OLDER_TEXT: "<literal>"` (a driver
that still plays a session in flight on the older text).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "tests" / "replay"
# Calls whose string arguments are text looked up in a command or agent file.
LOOKUPS = {"section", "blocks", "block", "inline_codes", "code", "codes", "template", "step_blocks",
           "run_step_blocks", "tpl", "item", "save_path", "heading"}
TEXT_KWARGS = {"anchor", "startswith", "contains", "heading"}
OLDER = re.compile(r'#\s*OLDER_TEXT:\s*"(.+?)"(?:\s|$)')
# (file, call) pairs whose string argument is not command text: dev_command's tpl/step_role take a step key that
# they map to today's sub-heading; merge's self.block(reason) records a block reason.
NOT_TEXT = {("dev_command.py", "tpl"), ("dev_command.py", "step_role"), ("merge.py", "block")}


def _fold(s: str) -> str:
    return " ".join(s.split())


def _today() -> str:
    parts = [p.read_text(encoding="utf-8") for d in ("commands", "agents") for p in sorted((ROOT / d).glob("*.md"))]
    return _fold("\n".join(parts))


def _sources() -> list[Path]:
    return sorted((REPLAY / "drivers").glob("*.py")) + sorted(REPLAY.glob("*.py"))


def _name(func: ast.expr) -> str:
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _is_lookup(node: ast.expr) -> bool:
    """A call to a lookup, possibly inside " ".join(<lookup>.split())."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _name(sub.func) in LOOKUPS:
            return True
    return False


def literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) in LOOKUPS \
                and (path.name, _name(node.func)) not in NOT_TEXT:
            args = list(node.args) + [k.value for k in node.keywords if k.arg in TEXT_KWARGS]
            out += [(node.lineno, a.value) for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) \
                    and any(_is_lookup(c) for c in node.comparators):
                out.append((node.lineno, node.left.value))
    return [(n, s) for n, s in out if s.strip() and not s.endswith(".md")]


def missing() -> list[str]:
    today = _today()
    bad = []
    for path in _sources():
        older = set(OLDER.findall(path.read_text(encoding="utf-8")))
        for line, lit in literals(path):
            if _fold(lit) not in today and lit not in older:
                bad.append(f"{path.relative_to(ROOT)}:{line}: {lit!r}")
    return bad


def test_collector_finds_lookups():
    """Positive control: the collector sees the drivers' lookups at all."""
    assert sum(len(literals(p)) for p in _sources()) > 100


def test_every_driver_literal_is_in_todays_text():
    bad = missing()
    assert not bad, "driver text gone from commands/ and agents/ (repair, or mark # OLDER_TEXT):\n" + "\n".join(bad)


if __name__ == "__main__":
    for p in _sources():
        for n, s in literals(p):
            print(f"{p.relative_to(ROOT)}:{n}\t{s}")
