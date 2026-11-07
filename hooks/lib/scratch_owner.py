#!/usr/bin/env python3
"""Whether a session scratch directory belongs to the session.

hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
it: the directory belongs to the session when that record exists and its `sid` is the
session's id. hooks/sessionend-scratch-sweep.sh removes the directory only then, and
doc-sync's notice keeps its dedupe state there only then, so the notice never writes into a
directory the sweep would leave behind.

Usage: scratch_owner.py <session-dir> <session-id>   (exit 0 when it belongs, 1 otherwise)
"""

import json
import os
import sys

OWNER_FILE = '.owner'


def owns_scratch_dir(session_dir, session_id) -> bool:
    if not session_id:
        return False
    try:
        with open(os.path.join(session_dir, OWNER_FILE), encoding='utf-8') as handle:
            record = json.load(handle)
    except Exception:
        return False
    return isinstance(record, dict) and record.get('sid') == session_id


if __name__ == '__main__':
    sys.exit(0 if len(sys.argv) == 3 and owns_scratch_dir(sys.argv[1], sys.argv[2]) else 1)
