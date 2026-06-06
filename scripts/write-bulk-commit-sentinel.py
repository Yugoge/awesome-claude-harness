#!/usr/bin/env python3
"""Write a multi-use /commit --bulk privilege-guard sentinel.

Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
changelog-analyst subagent to make multiple auto-bulk commits within a
single /commit --bulk session.

Unlike the single-use commit grant written for non-bulk commits, this
sentinel is NOT consumed on each validation — it persists until expiry
so that changelog-analyst can commit one subsystem group at a time.

File: /tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json
Contents: {kind, sid, nonce, created_at, expires_at}

The privilege guard checks for this file inside _evaluate_commit when
the commit message matches BLESSED_BRIDGE_RE. Without a valid sentinel,
auto-bulk commits are BLOCKED even if the message prefix is correct.

Exit codes:
  0  success (sentinel written; path printed to stdout)
  2  CLAUDE_SESSION_ID unresolved
"""

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SENTINEL_TTL_MINUTES = 30


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="write-bulk-commit-sentinel.py",
        description="Write a multi-use /commit --bulk privilege-guard sentinel.",
    )
    parser.add_argument(
        "--sid",
        default=None,
        help="Claude session id. Defaults to the CLAUDE_SESSION_ID env var.",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp",
        help="Directory to write the sentinel JSON into. Default: /tmp.",
    )
    parser.add_argument(
        "--origin",
        default="cli",
        help=(
            "Provenance marker recorded in the sentinel. The trusted "
            "userpromptsubmit-bulk-commit-capability hook passes "
            "'userpromptsubmit-hook'; standalone CLI invocation defaults to "
            "'cli'. A future privilege-guard provenance check (staged "
            "lockdown) may require origin=='userpromptsubmit-hook'."
        ),
    )
    return parser.parse_args(argv)


def _resolve_sid(cli_sid):
    if cli_sid:
        return cli_sid
    env_sid = os.environ.get("CLAUDE_SESSION_ID", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not env_sid:
        print(
            "Cannot write bulk-commit sentinel: CLAUDE_SESSION_ID and CLAUDE_CODE_SESSION_ID are not set and "
            "--sid was not supplied. Invoke /commit --bulk from within a Claude "
            "Code session or pass --sid explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)
    return env_sid


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    sid = _resolve_sid(args.sid)

    # Authorization: /commit --bulk has disable-model-invocation: true, so
    # reaching this script already proves human invocation. No separate auth
    # flag is required — the slash-command gate is the sole authorization check.
    nonce = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    sentinel = {
        "kind": "bulk-commit",
        "sid": sid,
        "nonce": nonce,
        "origin": args.origin,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=SENTINEL_TTL_MINUTES)).isoformat(),
    }
    path = Path(args.output_dir) / f"claude-bulk-commit-sentinel-{sid}-{nonce}.json"
    with open(path, "w") as fp:
        json.dump(sentinel, fp)
    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
