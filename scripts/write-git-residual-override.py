#!/usr/bin/env python3
"""Issue a HUMAN residual override for one git command the guard could not parse.

Answers the "could not be statically classified" refusal emitted by
hooks/pretool-git-privilege-guard.py. That refusal fires before the invocation
list and cannot be reached by an /allow grant (the command has no parseable
operation to match), so this is the only route out of it besides re-writing the
command with its binary spelled literally -- which is the cheaper fix and should
always be tried first.

Usage:
  write-git-residual-override.py --command-sha256 <hex> --residual-kinds <k[,k]>
                                 --reason <text> [--authorized-by <who>]
                                 [--ttl-minutes <n>] [--session-id <sid>]
                                 [--dir <namespace>]

Exit codes: 0=override written, 1=refused (bad input or agent context), 2=usage.

The override is bound to the FULL command text by digest, is single-use, and
expires. It does NOT grant the command: the guard clears only the unparseable-
token refusal and then applies every other policy check as usual.

Refuses to run when an agent identity is present in the environment. That is a
narrowing, not a guarantee -- a grant under /tmp is an ordinary file and this
repository has measured that an agent can mint one directly (route_id
"grant-self-minting" in hooks/tests/fixtures/overwrite_corpus.json). The
enforceable property is that every use is recorded in the transcript.
"""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DIR = "/tmp/claude-git-residual-override"
DEFAULT_TTL_MINUTES = 15
MAX_TTL_MINUTES = 60
VALID_KINDS = {"obfuscated_git_token", "dynamic_git_token", "substituted_git_token"}
AGENT_ENV_VARS = ("CLAUDE_AGENT_ID", "CLAUDE_SUBAGENT_ID")


def _fail(msg):
    sys.stderr.write("REFUSED: %s\n" % msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--command-sha256", required=True,
                    help="digest printed by the guard's refusal message")
    ap.add_argument("--residual-kinds", required=True,
                    help="comma-separated kinds from the refusal message")
    ap.add_argument("--reason", required=True,
                    help="why this command must run exactly as written")
    ap.add_argument("--authorized-by", default="")
    ap.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)
    ap.add_argument("--session-id", default=os.environ.get("CLAUDE_SESSION_ID", ""))
    ap.add_argument("--dir", default=DEFAULT_DIR,
                    help="override namespace (tests point this at scratch)")
    args = ap.parse_args()

    for var in AGENT_ENV_VARS:
        if os.environ.get(var):
            _fail("%s is set. An agent cannot authorize its own override; ask "
                  "your user to run this." % var)

    digest = args.command_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        _fail("--command-sha256 must be the 64-hex digest from the refusal "
              "message, verbatim.")

    kinds = sorted({k.strip() for k in args.residual_kinds.split(",") if k.strip()})
    if not kinds:
        _fail("--residual-kinds must name at least one kind.")
    unknown = sorted(set(kinds) - VALID_KINDS)
    if unknown:
        _fail("unknown residual kind(s): %s (expected any of %s)"
              % (", ".join(unknown), ", ".join(sorted(VALID_KINDS))))

    reason = args.reason.strip()
    if len(reason) < 20:
        _fail("--reason must be a real justification (>= 20 chars); it is "
              "written into the audit record that survives this session.")

    ttl = args.ttl_minutes
    if not 1 <= ttl <= MAX_TTL_MINUTES:
        _fail("--ttl-minutes must be between 1 and %d." % MAX_TTL_MINUTES)

    who = args.authorized_by.strip()
    if not who:
        try:
            who = "human:%s@%s" % (getpass.getuser(), os.uname().nodename)
        except Exception:
            who = "human:unknown"

    now = datetime.now(timezone.utc)
    record = {
        "kind": "git-residual-override",
        "origin": "userpromptsubmit-hook",
        "authorized_by": who,
        "reason": reason,
        "session_id": args.session_id,
        "command_sha256": digest,
        "residual_kinds": kinds,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl)).isoformat(),
    }

    ns = Path(args.dir)
    ns.mkdir(parents=True, exist_ok=True)
    path = ns / ("override-%s.json" % digest[:16])
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    sys.stderr.write(
        "Residual override written: %s\n"
        "  bound to command sha256 : %s\n"
        "  kinds authorized        : %s\n"
        "  authorized by           : %s\n"
        "  expires                 : %s (single-use)\n"
        "It will be honored only for a command the guard has ALREADY refused, "
        "and only once. Every other git policy check still applies.\n"
        % (path, digest, ", ".join(kinds), who, record["expires_at"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
