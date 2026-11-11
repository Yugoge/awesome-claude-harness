#!/usr/bin/env python3
"""PostToolUseFailure: record consumed Bash grants and attempted Codex Skill calls."""
from __future__ import annotations

import os
import sys

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
