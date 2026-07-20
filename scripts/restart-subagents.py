#!/usr/bin/env python3
"""CLI bridge for the human-only /restart recovery workflow."""

from __future__ import annotations

import argparse
import json
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
        command.add_argument("--session-id", required=True)
        if name == "status":
            command.add_argument("--wait-seconds", type=int, default=0)
    message = sub.add_parser("message")
    message.add_argument("--session-id", required=True)
    message.add_argument("--agent-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = restart.prepare_state(args.session_id)
        elif args.command == "status":
            result = restart.get_status(args.session_id, wait_seconds=max(0, args.wait_seconds))
        elif args.command == "message":
            result = {
                "agent_id": args.agent_id,
                "message": restart.build_resume_message(args.session_id, args.agent_id),
            }
        else:
            result = restart.finalize(args.session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except restart.RestartError as exc:
        print(json.dumps({"error": str(exc), "command": args.command}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

