#!/usr/bin/env python3
"""PostToolUse (every tool): the event's Python hooks in one process (lib/hook_launch.py).

Every Python hook registered on PostToolUse runs here, in its old registration order, each as
`python3 <file>` would have run it (its own timeout and failure direction), and the answer is
the one the CLI gave for those hooks together. A new PostToolUse Python hook is one Rule line below,
at the place its registration would have had: its file, its matcher's tool names, its timeout
(default 60 s); this file's registered timeout in settings.json is the sum of the rules'.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lib.hook_launch import Rule, main
except Exception:  # the hooks still run, each as its own process
    from lib.hook_launch_fallback import Rule, main

EVENT = "PostToolUse"
RULES = (
    Rule('allowlist-consume', 'posttool-allowlist-consume.py', matcher_spelling='*'),
    Rule('todo-tracker', 'posttool-todo-tracker.py', ('TodoWrite',)),
    Rule('overnight-loop', 'posttool-overnight-loop.py', ('TodoWrite',)),
    Rule('attribution-post', 'posttool-attribution-post.py', ('Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'), timeout=30),
    Rule('doc-sync', 'posttool-doc-sync.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit')),
    Rule('command-frontmatter-validate', 'posttool-command-frontmatter-validate.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit')),
    Rule('lane-completeness-watch', 'posttool-lane-completeness-watch.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit')),
    Rule('dispatch-record', 'posttool-dispatch-record.py', ('Agent',)),
    Rule('restart-sendmessage', 'posttool-restart-sendmessage.py', ('SendMessage',)),
    Rule('runcode-watchdog', 'posttool-runcode-watchdog.py', ('mcp__playwright__browser_run_code',)),
    Rule('codex-skill-ledger', 'posttool-codex-skill-ledger.py', ('Skill',)),
    Rule('close-rating', 'posttool-close-rating.py', ('AskUserQuestion', 'Agent')),
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
