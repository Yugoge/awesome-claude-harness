#!/usr/bin/env python3
"""Bootstrap steps 1, 2 and 4 of /paseo-daemon: ledger, timers, lease, account records.

    paseo-bootstrap.py start    --holder ID [--root DIR] [--ttl-seconds N] [--accounts A,B]
                                [--registry-dir DIR] [--controller-agent-id ID] [--prompts-dir DIR]
    paseo-bootstrap.py accounts --caller-id ID --reset NAME=INSTANT [--reset NAME=INSTANT ...]
                                [--root DIR]

--root defaults to .claude/paseo-daemon (the ledger directory of the command). Facts go to stdout as
key=value lines, one per line; the CLIs' own output is read, never echoed. Every state below is a fact,
never a failure: the exit status is 0 unless the arguments are wrong (2).

start     Runs, in this order and stopping at the first one that fails, the three calls Bootstrap
          Steps 1 and 2 name: `paseo-daemon-ledger.py init` (accounts from --accounts, else
          $PASEO_DAEMON_ACCOUNTS), `paseo-daemon-timers.py ensure`, `paseo-daemon-ledger.py
          lease-acquire --holder ID`. --registry-dir, --controller-agent-id and --prompts-dir go to
          `ensure` as given (the registry defaults to the real one when --registry-dir is absent);
          --ttl-seconds goes to lease-acquire.
          Prints status=ok|failed, failed_at=none|init|timers|lease, root, then per call
          init=ok|failed|skipped, timers=ok|failed|skipped, lease=acquired|refused|failed|skipped,
          each with <call>_exit and, on a failure, <call>_message (the last line the CLI wrote to
          stderr). After `ensure`: timers_created, timers_deviations (a comma list of timer keys,
          or none; a deviation is a timer found paused) and timers_json (what `ensure` printed).
          After lease-acquire: lease_holder, lease_incarnation. `refused` means another holder's
          lease has not expired.
accounts  Runs `paseo-daemon-ledger.py account-init` once per --reset, each with --caller-id ID,
          in the order given, and does not stop at a failure. Prints status=ok|failed (failed when
          any account failed) and, per account, account_<NAME>=ok|failed with account_<NAME>_message
          on a failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
LEDGER = HARNESS_ROOT / "scripts" / "paseo-daemon-ledger.py"
TIMERS = HARNESS_ROOT / "scripts" / "paseo-daemon-timers.py"
DEFAULT_ROOT = ".claude/paseo-daemon"


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def run(cmd: list[str]) -> tuple[int, dict | None, str]:
    """Run one CLI; return (exit status, the JSON object it printed last or None, last stderr line).

    The last line is the error: the ledger may print warnings before it."""
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    document = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            document = parsed
            break
    lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    return proc.returncode, document, lines[-1] if lines else ""


def ledger(root: str, *args: str) -> list[str]:
    return [sys.executable, str(LEDGER), "--root", root, *args]


def keys_of(items: object) -> str:
    keys = [str(item.get("key")) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return ",".join(keys) or "none"


def start(args: argparse.Namespace) -> None:
    root = args.root
    facts: dict[str, object] = {"root": root, "init": "skipped", "timers": "skipped", "lease": "skipped"}

    init_cmd = ledger(root, "init")
    if args.accounts is not None:
        init_cmd += ["--accounts", args.accounts]
    code, _, message = run(init_cmd)
    facts.update(init="ok" if code == 0 else "failed", init_exit=code)
    if code != 0:
        emit(status="failed", failed_at="init", **facts, init_message=message)
        return

    timers_cmd = [sys.executable, str(TIMERS)]
    if args.registry_dir is not None:
        timers_cmd += ["--registry-dir", args.registry_dir]
    timers_cmd.append("ensure")
    for flag, value in (("--controller-agent-id", args.controller_agent_id), ("--prompts-dir", args.prompts_dir)):
        if value is not None:
            timers_cmd += [flag, value]
    code, document, message = run(timers_cmd)
    facts.update(timers="ok" if code == 0 else "failed", timers_exit=code)
    if code != 0:
        emit(status="failed", failed_at="timers", **facts, timers_message=message)
        return
    document = document or {}
    facts.update(timers_created=keys_of(document.get("created")),
                 timers_deviations=keys_of(document.get("deviations")),
                 timers_json=json.dumps(document, sort_keys=True))

    lease_cmd = ledger(root, "lease-acquire", "--holder", args.holder)
    if args.ttl_seconds is not None:
        lease_cmd += ["--ttl-seconds", str(args.ttl_seconds)]
    code, document, message = run(lease_cmd)
    if code == 0 and document:
        facts.update(lease="acquired", lease_exit=code, lease_holder=document.get("holder"),
                     lease_incarnation=document.get("incarnation"))
        emit(status="ok", failed_at="none", **facts)
        return
    # exit 2 is the CLI's refusal: another holder's lease has not expired
    facts.update(lease="refused" if code == 2 else "failed", lease_exit=code)
    emit(status="failed", failed_at="lease", **facts, lease_message=message)


def accounts(args: argparse.Namespace) -> None:
    results: dict[str, object] = {}
    failed = False
    for name, instant in args.reset:
        code, _, message = run(ledger(args.root, "account-init", "--account", name,
                                      "--weekly-reset", instant, "--caller-id", args.caller_id))
        results[f"account_{name}"] = "ok" if code == 0 else "failed"
        if code != 0:
            failed = True
            results[f"account_{name}_message"] = message
    emit(status="failed" if failed else "ok", root=args.root, **results)


def reset_pair(text: str) -> tuple[str, str]:
    name, sep, instant = text.partition("=")
    if not sep or not name or not instant:
        raise argparse.ArgumentTypeError(f"expected NAME=INSTANT, got {text!r}")
    return name, instant


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start")
    s.add_argument("--holder", required=True, help="lease holder: this controller's incarnation id")
    s.add_argument("--root", default=DEFAULT_ROOT)
    s.add_argument("--ttl-seconds", type=int, default=None)
    s.add_argument("--accounts", default=None, help="comma-separated names; default $PASEO_DAEMON_ACCOUNTS")
    s.add_argument("--registry-dir", default=None)
    s.add_argument("--controller-agent-id", default=None)
    s.add_argument("--prompts-dir", default=None)
    s.set_defaults(fn=start)

    s = sub.add_parser("accounts")
    s.add_argument("--caller-id", required=True, help="the lease holder")
    s.add_argument("--reset", action="append", required=True, type=reset_pair, metavar="NAME=INSTANT")
    s.add_argument("--root", default=DEFAULT_ROOT)
    s.set_defaults(fn=accounts)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
