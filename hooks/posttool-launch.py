#!/usr/bin/env python3
"""PostToolUse (every tool): the event's Python hooks in one process (lib/hook_launch.py).

Every Python hook registered on PostToolUse runs here, each as `python3 <file>` would have run it
(its own timeout and failure direction), those a call matches at the same time, each in a fork
of this process (a rule with ``after`` starts once the earlier rules it names have ended), and
the answer is the one the CLI gave for those hooks together, read in the table's order (their
old registration order). A new PostToolUse Python hook is one Rule line below, at the place its
registration would have had: its file, its matcher's tool names, its timeout (default 60 s),
and ``after`` when it reads what an earlier rule of the same call writes (or writes what one
reads); this file's registered timeout in settings.json is the sum of the rules'.
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
from lib.subagent import DISPATCH_TOOLS  # the dispatch tool names, one list for every reader

EVENT = "PostToolUse"
RULES = (
    Rule('orchestrator-ran', 'posttool-orchestrator-ran.py', timeout=10),  # the calls that ran (pretool-orchestrator-gate.py)
    Rule('allowlist-consume', 'posttool-allowlist-consume.py', matcher_spelling='*'),
    Rule('todo-tracker', 'posttool-todo-tracker.py', ('TodoWrite',)),
    Rule('overnight-loop', 'posttool-overnight-loop.py', ('TodoWrite',)),
    Rule('attribution-post', 'posttool-attribution-post.py', ('Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'), timeout=30),
    Rule('doc-sync', 'posttool-doc-sync.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit'),
         after=('attribution-post',)),  # rewrites the CLAUDE.md attribution-post hashes
    Rule('command-frontmatter-validate', 'posttool-command-frontmatter-validate.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit')),
    Rule('lane-completeness-watch', 'posttool-lane-completeness-watch.py', ('Write', 'Edit', 'NotebookEdit', 'MultiEdit')),
    Rule('dispatch-record', 'posttool-dispatch-record.py', DISPATCH_TOOLS),
    Rule('restart-sendmessage', 'posttool-restart-sendmessage.py', ('SendMessage',)),
    Rule('runcode-watchdog', 'posttool-runcode-watchdog.py', ('mcp__playwright__browser_run_code',)),
    Rule('codex-skill-ledger', 'posttool-codex-skill-ledger.py', ('Skill',)),
    Rule('close-rating', 'posttool-close-rating.py', ('AskUserQuestion', *DISPATCH_TOOLS)),
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
