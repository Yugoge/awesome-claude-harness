#!/usr/bin/env python3
"""PostToolUse hook: append the attribution event(s) for a finished mutation.

Pairs with pretool-attribution-pre.py via (session_id, tool_use_id). Purely
observational: never blocks, always exits 0, fails soft.

Also the sole production trigger for the periodic seal-to-persistent-storage
step (autoseal_hook_trigger -- see hooks/lib/attribution_journal.py and
docs/reference/attribution-journal-phase0-facility.md #1): it runs after
record_post, in its own fail-soft path, so a seal failure never affects
capture and a capture failure never blocks the seal check.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        from lib.attribution_journal import record_post
        record_post(payload)
    except Exception:
        pass
    try:
        from lib.attribution_journal import autoseal_hook_trigger
        autoseal_hook_trigger()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
