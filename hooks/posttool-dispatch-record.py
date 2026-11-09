#!/usr/bin/env python3
"""PostToolUse (Agent): one process for what a returned dispatch records and checks.

The rules run in this order, each as its own hook would run alone
(hooks/lib/gate_runner.py):

1. posttool-subagent-track.py: on the PM TRIAGE return, the cycle contract's one
   writer;
2. posttool-overnight-file-check.py: the returned producer's artifacts against the
   cycle contract (exit 2 returns the finding to the agent);
3. posttool-overnight-trace.py: the overnight trace record.

The contract is written before the two rules that read it, so neither reads it half
way through a write or before it exists on the same return, as they did when the
three ran side by side.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

from lib.gate_runner import OBSERVE, REFUSE, Rule, main  # noqa: E402

RULES = [
    Rule("cycle-contract-writer", str(HOOKS / "posttool-subagent-track.py"), OBSERVE),
    Rule("overnight-file-check", str(HOOKS / "posttool-overnight-file-check.py"), REFUSE),
    Rule("overnight-trace", str(HOOKS / "posttool-overnight-trace.py"), OBSERVE),
]

if __name__ == "__main__":
    sys.exit(main(RULES))
