"""The harness's own vocabulary is written once and every consumer reads it.

Each test below pins one fact the 2026-11-19 duplicate audit found written in several places
whose copies answered the same question differently (a defect family), on the inputs on which
the copies disagreed: after the merge every consumer gives the same answer, and no consumer
holds a copy of its own.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
SOURCES = [p for d in ("hooks", "scripts") for p in sorted((ROOT / d).rglob("*.py"))
           if "tests" not in p.relative_to(ROOT).parts and "__pycache__" not in p.parts]


def _lib(name: str):
    sys.path.insert(0, str(HOOKS))
    try:
        return __import__(f"lib.{name}", fromlist=["_"])
    finally:
        sys.path.pop(0)


def _string_tables(path: Path):
    """(line, members) of every tuple/set/list literal of two or more strings, and of every
    `x == "a" or x == "b"` / `!= and !=` chain, in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.Set, ast.List)):
            vals = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vals) >= 2 and len(vals) == len(node.elts):
                yield node.lineno, frozenset(vals)
        elif isinstance(node, ast.BoolOp):
            vals = [c.comparators[0].value for c in node.values
                    if isinstance(c, ast.Compare) and len(c.ops) == 1 and isinstance(c.ops[0], (ast.Eq, ast.NotEq))
                    and isinstance(c.comparators[0], ast.Constant) and isinstance(c.comparators[0].value, str)]
            if len(vals) >= 2:
                yield node.lineno, frozenset(vals)


def _copies(members: set, home: str) -> list[str]:
    """Every literal table of exactly `members` in hooks/ and scripts/ outside `home`."""
    want = frozenset(members)
    return [f"{p.relative_to(ROOT)}:{line}" for p in SOURCES if str(p.relative_to(ROOT)) != home
            for line, vals in _string_tables(p) if vals == want]


# ---------------------------------------------------------------- tool-subagent-dispatch
DISPATCH = {"Agent", "Task"}  # "Agent", and "Task", the name the CLI used before and still accepts


def test_dispatch_tool_names_are_defined_once():
    assert set(_lib("subagent").DISPATCH_TOOLS) == DISPATCH
    assert _copies(DISPATCH, "hooks/lib/subagent.py") == []


def test_launchers_select_the_dispatch_rules_for_every_dispatch_name():
    """The audit's input: tool_name=Task. The launchers selected dispatch-gate, dispatch-record and
    close-rating for "Agent" only, while every hook of those rules answers for both names."""
    launch_settings = _lib("launch_settings")
    seen = []
    for launcher in ("hooks/pretool-launch.py", "hooks/posttool-launch.py"):
        for path, tools, _timeout in launch_settings.rules(str(ROOT), launcher):
            if tools is not None and DISPATCH & set(tools):
                seen.append(path)
                assert DISPATCH <= set(tools), f"{launcher}: {path} selects {tools}"
    assert {"pretool-dispatch-gate.py", "posttool-dispatch-record.py", "posttool-close-rating.py"} <= set(seen)
