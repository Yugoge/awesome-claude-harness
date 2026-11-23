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
       scratch_owner.py --root                       (prints the session scratch root, for the shell scripts)
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


def owner_record(session_dir):
    """The record of `session_dir`/.owner, None when it is missing, unreadable or not an object: the one
    reader of the record (overwrite_scope, dispatch_temp and policy_registry take it from here)."""
    try:
        with open(os.path.join(session_dir, OWNER_FILE), encoding='utf-8') as handle:
            record = json.load(handle)
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def owns_scratch_dir(session_dir, session_id) -> bool:
    record = owner_record(session_dir) if session_id else None
    return record is not None and record.get('sid') == session_id


if __name__ == '__main__':
    if sys.argv[1:] == ['--root']:  # the shell scripts' root: the one definition, locations.session_scratch_root
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import locations
        print(locations.session_scratch_root())
        sys.exit(0)
    if sys.argv[1:2] == ['--safe-sid']:
        sys.exit(0 if len(sys.argv) > 2 and all(map(is_safe_session_dir_name, sys.argv[2:])) else 1)
    sys.exit(0 if len(sys.argv) == 3 and owns_scratch_dir(sys.argv[1], sys.argv[2]) else 1)
