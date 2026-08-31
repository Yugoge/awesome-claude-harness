#!/usr/bin/env python3
"""CLI bridge for the human-only /restart recovery workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import subagent_restart as restart  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover quota-interrupted Claude Code subagents")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "status", "finalize"):
        command = sub.add_parser(name)
        command.add_argument("--session-id")
        if name == "status":
            command.add_argument("--wait-seconds", type=int, default=0)
    propose = sub.add_parser("propose-unrecoverable")
    propose.add_argument("--session-id")
    propose.add_argument("--tool-use-id", required=True)
    propose.add_argument("--agent-id", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--evidence-ref", action="append", required=True)
    mark = sub.add_parser("mark-unrecoverable")
    mark.add_argument("--session-id")
    mark.add_argument("--audit-id", required=True)
    return parser


def _session_id(explicit: str | None) -> str:
    session_id = explicit or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get(
        "CLAUDE_SESSION_ID"
    )
    if not session_id:
        raise restart.RestartError("RESTART_BLOCKED_SESSION_ID_UNAVAILABLE")
    return session_id


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        session_id = _session_id(args.session_id)
        if args.command == "prepare":
            result = restart.prepare_state(session_id)
        elif args.command == "status":
            result = restart.get_status(session_id, wait_seconds=max(0, args.wait_seconds))
        elif args.command == "propose-unrecoverable":
            try:
                evidence_refs = [json.loads(value) for value in args.evidence_ref]
            except ValueError as exc:
                raise restart.RestartError("evidence-ref must be canonical JSON") from exc
            result = restart.propose_unrecoverable(
                session_id, args.tool_use_id, args.agent_id, args.reason, evidence_refs,
            )
        elif args.command == "mark-unrecoverable":
            result = restart.mark_unrecoverable(session_id, args.audit_id)
        else:
            result = restart.finalize(session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except restart.RestartError as exc:
        print(json.dumps({"error": str(exc), "command": args.command}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
