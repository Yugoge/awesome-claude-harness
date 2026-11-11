#!/usr/bin/env python3
"""PostToolUseFailure: record consumed Bash grants and attempted Codex Skill calls."""
from __future__ import annotations
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lib.hook_launch import Rule, main
except Exception:
    from lib.hook_launch_fallback import Rule, main

EVENT = "PostToolUseFailure"
RULES = (
    Rule('allowlist-consume', 'posttool-allowlist-consume.py', ('Bash',)),
    Rule('codex-skill-ledger', 'posttool-codex-skill-ledger.py', ('Skill',)),
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
