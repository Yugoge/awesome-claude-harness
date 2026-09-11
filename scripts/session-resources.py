#!/usr/bin/env python3
"""Provider-neutral CLI for the LANE-B session resource broker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HOOKS = Path(__file__).resolve().parents[1] / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from lib import session_resources


def _load_binding(args: argparse.Namespace) -> dict:
    if args.binding_json:
        value = json.loads(args.binding_json)
    else:
        value = json.loads(Path(args.binding).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise session_resources.ResourceError("binding must be a JSON object")
    return value


def _command(values: list[str]) -> list[str]:
    return values[1:] if values and values[0] == "--" else values


def _emit(value: dict) -> int:
    print(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return 0 if value.get("status") == "pass" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    sub = parser.add_subparsers(dest="operation", required=True)

    for name in ("provision", "exec", "spawn"):
        item = sub.add_parser(name)
        source = item.add_mutually_exclusive_group(required=True)
        source.add_argument("--binding")
        source.add_argument("--binding-json")
        if name in {"exec", "spawn"}:
            item.add_argument("command", nargs=argparse.REMAINDER)

    status = sub.add_parser("status")
    status.add_argument("--resource-session", required=True)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--claude-session", required=True)
    finalize.add_argument("--resource-session", required=True)
    finalize.add_argument("--term-timeout", type=float, default=1.0)
    finalize.add_argument("--kill-timeout", type=float, default=1.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.operation == "provision":
            result = session_resources.provision(args.project_dir, _load_binding(args))
        elif args.operation == "exec":
            command = _command(args.command)
            result = session_resources.exec_owned(
                args.project_dir, _load_binding(args), command
            )
        elif args.operation == "spawn":
            command = _command(args.command)
            result = session_resources.spawn_owned(
                args.project_dir, _load_binding(args), command
            )
        elif args.operation == "status":
            result = session_resources.status(
                args.project_dir, args.resource_session
            )
        else:
            result = session_resources.finalize(
                args.project_dir,
                claude_session_id=args.claude_session,
                resource_session_id=args.resource_session,
                term_timeout=args.term_timeout,
                kill_timeout=args.kill_timeout,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "status": "fail",
            "error_code": "resource_contract_error",
            "message": str(exc),
        }
    return _emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
