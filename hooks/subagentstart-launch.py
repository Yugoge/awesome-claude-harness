#!/usr/bin/env python3
"""SubagentStart: the event's Python hooks in one process (lib/hook_launch.py).

Every Python hook registered on SubagentStart runs here, each as `python3 <file>` would have run it
(its own timeout and failure direction), at the same time, each in a fork of this process (a rule
with ``after`` starts once the earlier rules it names have ended), and the answer is the one the
CLI gave for those hooks together, read in the table's order: subagentstart-record.py's record of
the agent and prompt-workflow.py's PROJECT_ROOT and HARNESS_ROOT lines (P2-3), one
additionalContext the CLI puts in the starting subagent's context; subagentstart-scratch.py makes the
agent's own scratch directory and prints nothing. None writes anything another reads, so none has ``after``. A new SubagentStart Python hook is one Rule line below, at
the place its registration would have had: its file, its timeout (default 60 s), and ``after``
when it reads what an earlier rule of the same call writes (or writes what one reads); this
file's registered timeout in settings.json is the sum of the rules'.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lib.hook_launch import Rule, main
except Exception:  # the hooks still run, each as its own process
    from lib.hook_launch_fallback import Rule, main

EVENT = "SubagentStart"
RULES = (
    Rule('record', 'subagentstart-record.py'),
    Rule('prompt-workflow', 'prompt-workflow.py'),
    Rule('scratch', 'subagentstart-scratch.py', timeout=5),  # the agent's own scratch directory: made, nothing printed
)

if __name__ == "__main__":
    sys.exit(main(EVENT, RULES))
