#!/usr/bin/env python3
"""
PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
when structural files change (it updates files that exist and creates none).

Delegates to doc_sync module. See doc_sync/ directory for implementation.
Hook type: PostToolUse (Write|Edit|NotebookEdit matcher)
Exit codes: 0 always (never blocks)
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

from doc_sync.main import main

if __name__ == '__main__':
    main()
