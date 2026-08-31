"""Guard: scripts/todo/dev.py must stay readable by the codex-native harness.

The harness never imports or executes the canonical checklist; it ``ast.parse``s
the file, requires ``get_todos`` to hold a SINGLE ``Return`` whose value is
``ast.literal_eval``-able, and rejects any item key outside a fixed whitelist.
Any violation degrades to an empty step table, which silently zeroes /dev
step-completion projection (frontier stuck at 0) instead of raising.

The contract is replicated inline rather than imported from
``/root/.codex/hooks/codex_native_harness.py`` so this guard stays hermetic and
sub-second; the e2e suite catches the same regression in ~50s.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_TODO = ROOT / "scripts/todo/dev.py"

ITEM_KEY_WHITELIST = {"content", "activeForm", "status", "subagent_call"}
LITERAL_STATUSES = {"pending", "in_progress", "completed"}
EXPECTED_ROLES = ["ba", "qa", "graphify", "dev", "qa"]


def _literal_todos() -> list[dict]:
    """Parse the checklist exactly the way the codex-native harness does."""
    module = ast.parse(DEV_TODO.read_text(encoding="utf-8"), filename=str(DEV_TODO))
    functions = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_todos"
    ]
    assert len(functions) == 1, "exactly one top-level get_todos must exist"
    returns = [node for node in functions[0].body if isinstance(node, ast.Return)]
    assert len(returns) == 1, (
        "get_todos must hold exactly one Return; the harness rejects anything "
        "else and falls back to an empty step table"
    )
    value = ast.literal_eval(returns[0].value)
    assert isinstance(value, list) and value, "returned literal must be a non-empty list"
    return value


def test_get_todos_returns_a_single_literal_the_harness_can_read():
    todos = _literal_todos()
    assert len(todos) == 9


def test_every_item_matches_the_harness_key_whitelist():
    for index, item in enumerate(_literal_todos()):
        assert isinstance(item, dict), f"item {index} is not a dict"
        extra = set(item) - ITEM_KEY_WHITELIST
        assert not extra, (
            f"item {index} carries non-whitelisted key(s) {sorted(extra)}; the "
            "harness returns [] on any extra key — put such metadata at module "
            "level instead (see PHASE_COVERS_OLD_STEPS)"
        )
        assert isinstance(item.get("content"), str)
        assert isinstance(item.get("activeForm"), str)
        assert item.get("status") in LITERAL_STATUSES


def test_subagent_call_shape_is_exact():
    roles = []
    for item in _literal_todos():
        call = item.get("subagent_call")
        if call is None:
            continue
        assert isinstance(call, dict)
        assert set(call) == {"agent", "subagent_type"}
        assert all(isinstance(call[key], str) for key in ("agent", "subagent_type"))
        roles.append(call["subagent_type"])
    assert roles == EXPECTED_ROLES


def test_literal_parse_matches_actual_execution():
    """What the harness reads statically must equal what /dev executes."""
    executed = json.loads(
        subprocess.run(
            [sys.executable, str(DEV_TODO)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert _literal_todos() == executed


def test_phase_coverage_metadata_lives_at_module_level():
    module = ast.parse(DEV_TODO.read_text(encoding="utf-8"), filename=str(DEV_TODO))
    assigned = {
        target.id
        for node in module.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "PHASE_COVERS_OLD_STEPS" in assigned
    coverage = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "PHASE_COVERS_OLD_STEPS"
            for target in node.targets
        )
    )
    assert sorted(coverage) == list(range(1, 10))
    flattened = [old for phase in sorted(coverage) for old in coverage[phase]]
    assert flattened == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 15, 17]
