"""The six checks by name, in the order the P12 plan lists them."""
from __future__ import annotations

from .hooks import check_two_writers, check_unreachable_output
from .prompts import check_dead_references, check_emphasis, check_hook_strength, check_repeated_blocks
from .tree import Finding, Tree

CHECKS = {
    "hook-strength": check_hook_strength,
    "dead-reference": check_dead_references,
    "repeated-block": check_repeated_blocks,
    "emphasis": check_emphasis,
    "unreachable-output": check_unreachable_output,
    "two-writers": check_two_writers,
}


def run(tree: Tree, names=None) -> dict[str, list[Finding]]:
    return {name: CHECKS[name](tree) for name in (names or CHECKS)}
