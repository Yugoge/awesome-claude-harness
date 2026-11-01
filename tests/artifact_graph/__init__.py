"""Static half of P1b's artifact check (row 19, E1).

``derive(tree)`` returns every relation, declaration, deciding candidate,
chain call, owner-facing output and rule-(7) candidate the static half finds
in a harness tree; see static_half.py.
"""

from .static_half import DEFAULT_CHAIN_SCRIPT, StaticResult, derive

__all__ = ["DEFAULT_CHAIN_SCRIPT", "StaticResult", "derive"]
