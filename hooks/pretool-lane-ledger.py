#!/usr/bin/env python3
"""PreToolUse: a dev lane's file baselines, recorded before its calls that may change files (lib/lane_ledger.py).

Observational: never blocks, always exits 0; a failure records nothing and the lane's stop finds less to complete.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

if __name__ == "__main__":
    try:
        from lib.lane_ledger import record
        record(json.load(sys.stdin))
    except Exception:
        pass
    sys.exit(0)
