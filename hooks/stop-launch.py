#!/usr/bin/env python3
"""The registered Stop hook (P5 R10): run the Stop coordinator, relay its exit 0 or 2, stdout and
stderr. When the coordinator cannot decide (another exit, a timeout, a launch error, a missing
file), decide alone on the two stdlib modules loaded by path, the transcript reader
(hooks/lib/command_span.py: the latest human-typed command, read over the whole transcript) and
the overnight window (hooks/lib/overnight.py's window_open), so a broken coordinator or
stop_contract.py leaves this file deciding: CLAUDE_COMMAND_GATE=off allows; an open window, or a
gated latest command, blocks naming the failure and /stop; else allow. The coordinator it runs is
marked (CLAUDE_STOP_LAUNCHER=1), which arms its gate (arming option 1). Stated loss: a
broken module it loads is the one case it cannot decide; its checks then count as not holding."""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib")); import harness_switch; sys.path.pop(0)  # noqa: E402,E702
harness_switch.exit_if_off()
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
COORDINATOR_TIMEOUT = 280  # under the registration's 300 s


def _load(name: str):
    try:
        spec = importlib.util.spec_from_file_location(name, HOOKS / "lib" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # overnight.py reaches the reader by this name
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _holds(check) -> bool:
    try:
        return bool(check())
    except Exception:
        return False


def fallback(raw: bytes, reason: str) -> int:
    if os.environ.get("CLAUDE_COMMAND_GATE", "") == "off":
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    reader, overnight = _load("command_span"), _load("overnight")
    window = _holds(lambda: overnight.window_open(payload))
    gated = _holds(lambda: reader.active_command(payload.get("transcript_path")) in reader.GATED_COMMANDS)
    if window or gated:
        sys.stderr.write(f"COMMAND_GATE instrument failure: {reason}. The gate is broken; the human can type /stop\n")
        return 2
    return 0


def main() -> int:
    raw = sys.stdin.buffer.read()
    name = "stop-workflow-coordinator.py"
    if not (HOOKS / name).is_file():  # python3 on a missing file exits 2, which is no decision
        return fallback(raw, f"{name} is missing")
    try:
        done = subprocess.run([sys.executable, str(HOOKS / "stop-workflow-coordinator.py")], input=raw,
                              capture_output=True, timeout=COORDINATOR_TIMEOUT,
                              env={**os.environ, "CLAUDE_STOP_LAUNCHER": "1"})  # it arms the gate
    except subprocess.TimeoutExpired:
        return fallback(raw, f"{name} ran past {COORDINATOR_TIMEOUT} s")
    except OSError as exc:
        return fallback(raw, f"{name} could not start ({type(exc).__name__})")
    if done.returncode not in (0, 2):
        last = (done.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        return fallback(raw, f"{name} exited {done.returncode}" + (f" ({last})" if last else ""))
    sys.stdout.buffer.write(done.stdout)
    sys.stderr.buffer.write(done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
