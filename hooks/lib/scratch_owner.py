#!/usr/bin/env python3
"""Whether a session scratch directory belongs to the session.

hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
it: the directory belongs to the session when that record exists and its `sid` is the
session's id. hooks/sessionend-scratch-sweep.sh removes the directory only then, and
doc-sync's notice keeps its dedupe state there only then, so the notice never writes into a
directory the sweep would leave behind.

It also holds the one rule for a session id used as a directory name (is_safe_session_dir_name):
the scratch init and sweep, the write gate's own-scratch rule, the orchestrator gate's scratch
check and doc-sync's notice all apply it before they join the id to a root.

Usage: scratch_owner.py <session-dir> <session-id>   (exit 0 when it belongs, 1 otherwise)
       scratch_owner.py --safe-sid <session-id>...   (exit 0 when each is a safe directory name)
"""

import json
import os
import re
import sys

OWNER_FILE = '.owner'
# A session id is a directory name below a root when it is 1-128 of these characters and holds
# no "..", so it is one path component that can never name the root or step out of it.
_SESSION_DIR_NAME = re.compile(r'[A-Za-z0-9_.-]{1,128}')


def is_safe_session_dir_name(session_id) -> bool:
    return (isinstance(session_id, str) and _SESSION_DIR_NAME.fullmatch(session_id) is not None
            and '..' not in session_id and session_id != '.')


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
    if sys.argv[1:2] == ['--safe-sid']:
        sys.exit(0 if len(sys.argv) > 2 and all(map(is_safe_session_dir_name, sys.argv[2:])) else 1)
    sys.exit(0 if len(sys.argv) == 3 and owns_scratch_dir(sys.argv[1], sys.argv[2]) else 1)
