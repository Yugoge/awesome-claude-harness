#!/usr/bin/env python3
"""PreToolUse hook: record pre-mutation content hash of each write target.

Phase 0 of the write-time attribution journal (see hooks/lib/attribution_journal.py).
Purely observational: never blocks, always exits 0, fails soft.
Paired with posttool-attribution-post.py; registered in settings.json and
settings.template.json.
"""
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
