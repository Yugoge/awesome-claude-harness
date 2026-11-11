#!/usr/bin/env python3
"""PreToolUse (every tool): the event's Python hooks in one process (lib/hook_launch.py).

Every Python hook registered on PreToolUse runs here, in its old registration order, each as
`python3 <file>` would have run it (its own timeout and failure direction), and the answer is
the one the CLI gave for those hooks together. A new PreToolUse Python hook is one Rule line below,
at the place its registration would have had: its file, its matcher's tool names, its timeout
(default 60 s); this file's registered timeout in settings.json is the sum of the rules'.
"""
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

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lib.hook_launch import Rule, main
except Exception:  # the hooks still run, each as its own process
    from lib.hook_launch_fallback import Rule, main

EVENT = "PreToolUse"
RULES = (
    Rule('orchestrator-gate', 'pretool-orchestrator-gate.py'),
    Rule('block-background-tasks', 'pretool-block-background-tasks.py'),
    Rule('do-block-subagents', 'pretool-do-block-subagents.py'),
    Rule('read-size-guard', 'pretool-read-size-guard.py'),
    Rule('workflow-gate', 'pretool-workflow-gate.py'),
    Rule('write-gate', 'pretool-write-gate.py', None, timeout=70, matcher_spelling='*'),
    Rule('wrapper-userintent', 'pretool-wrapper-userintent.py', ('Bash',)),
    Rule('grep-backtrack-guard', 'pretool-grep-backtrack-guard.py', ('Bash',)),
    Rule('cp-checkin', 'pretool-cp-checkin.py', ('Read',)),
    Rule('quality-gate', 'pretool-quality-gate.py', ('Write', 'Edit', 'MultiEdit')),
    Rule('attribution-pre', 'pretool-attribution-pre.py', ('Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'), timeout=30),
    Rule('todo-validate', 'pretool-todo-validate.py', ('TodoWrite',)),
    Rule('block-branch-pr-worktree', 'pretool-block-branch-pr-worktree.py', ('Bash',)),
    Rule('dispatch-gate', 'pretool-dispatch-gate.py', ('Agent',)),
    Rule('runcode-watchdog', 'pretool-runcode-watchdog.py', ('mcp__playwright__browser_run_code',)),
    Rule('bulk-commit-detector', 'pretool-bulk-commit-detector.py', ('Bash',), timeout=5),
    Rule('git-privilege-guard', 'pretool-git-privilege-guard.py', ('Bash',)),
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
