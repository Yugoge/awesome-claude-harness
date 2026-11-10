#!/usr/bin/env python3
"""UserPromptSubmit: the event's Python hooks in one process (lib/hook_launch.py).

Every Python hook registered on UserPromptSubmit runs here, in its old registration order, each as
`python3 <file>` would have run it (its own timeout and failure direction), and the answer is
the one the CLI gave for those hooks together. A new UserPromptSubmit Python hook is one Rule line below,
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

EVENT = "UserPromptSubmit"
RULES = (
    Rule('prompt-workflow', 'prompt-workflow.py'),
    Rule('doc-sync-check', 'userprompt-doc-sync-check.py'),
    Rule('restart-authorize', 'userprompt-restart-authorize.py'),
    Rule('bulk-commit-capability', 'userprompt-bulk-commit-capability.py'),
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
