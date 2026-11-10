#!/usr/bin/env python3
"""PreToolUse hook: record pre-mutation content hash of each write target.

Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py).
Purely observational: never blocks, always exits 0, fails soft.
Paired with posttool-attribution-post.py; registered in settings.json.
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
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        from lib.attribution_journal import record_pre
        record_pre(payload)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
