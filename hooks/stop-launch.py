#!/usr/bin/env python3
"""The registered Stop hook (P5 R10): run the Stop coordinator, relay its exit 0 or 2, stdout and
stderr. When the coordinator cannot decide (another exit, a timeout, a launch error, a missing
file), decide alone on the two stdlib modules loaded by path, the transcript reader
(hooks/lib/command_span.py: the latest human-typed command, read over the whole transcript) and
the overnight window (hooks/lib/overnight.py's window_open), so a broken coordinator or
stop_contract.py leaves this file deciding: CLAUDE_COMMAND_GATE=off allows; a gated latest command,
the overnight window open or not, while a background child of it runs, as the gate reads it (stop-command-gate.py's
waiting_for, loaded by path), is a wait: exit 0 naming the failure and the child; else an open window, or a
gated latest command, blocks naming the failure and /stop (a coordinator out of time: no verdict,
the next stop continues the gate's work, as the coordinator says of its gate); else allow. Those three facts are read
within READ_LIMIT; a record not read in time blocks with the same text, nothing verified, and so does a transcript
reader or overnight module that cannot be loaded (the text then names it and why, and the refusal record holds that text).
The coordinator it runs is marked (CLAUDE_STOP_LAUNCHER=1), which arms its gate (arming option 1). Stated loss: a
broken stop-command-gate.py leaves its wait reading out (no running child is seen)."""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
COORDINATOR_TIMEOUT = 280  # with READ_LIMIT and RECORD_LIMIT under the registration's 300 s: 280 + 5 + 10 = 295
READ_LIMIT = 5  # what fallback's reading of the session record may cost (_facts in a daemon thread)
RECORD_LIMIT = 10  # what record's process may cost
FAILED: dict = {}  # a module _load could not load -> why (the fallback names it)
RECORDER = HOOKS / "lib" / "refusal_record.py"  # the refusal record's writer, a process of its own (record)


def _load(name: str, path: Path | None = None):
    try:
        spec = importlib.util.spec_from_file_location(name, path or HOOKS / "lib" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # overnight.py reaches the reader by this name
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        sys.modules.pop(name, None)
        FAILED[name] = f"{type(exc).__name__}: {exc}"[:300]
        return None


def _texts(reason: str, limit: float | None) -> tuple[str, str]:
    """(head, tail) of the fallback's text; a coordinator out of time (``limit`` its seconds) says what
    stop-workflow-coordinator.py's no_verdict_text says of the gate out of time."""
    if limit is None:
        return f"COMMAND_GATE instrument failure: {reason}", ". The gate is broken; the human can type /stop\n"
    return (f"COMMAND_GATE: {reason} ran out of time after {limit:g} s and has no verdict",
            ", so this stop is not let through as complete. The gate keeps what it computed, so the next stop "
            "continues from there. The owner can end the command with /stop.\n")


def _facts(payload: dict) -> tuple[bool, bool, list]:
    """(overnight window open, latest human-typed command gated, its running background children). A module
    not loaded or a reading that raises (FAILED names it) leaves nothing verified: the reading of a coordinator with no verdict."""
    reader, overnight = _load("command_span"), _load("overnight")
    if reader is None or overnight is None:
        return True, True, []
    try:  # a reading that raises is a reading not made, as a module not loaded is
        window = bool(overnight.window_open(payload))
    except Exception as exc:
        FAILED["overnight"] = f"{type(exc).__name__}: {exc}"[:300]
        return True, True, []
    try:
        gated = reader.active_command(payload.get("transcript_path")) in reader.GATED_COMMANDS
    except Exception as exc:
        FAILED["command_span"] = f"{type(exc).__name__}: {exc}"[:300]
        return True, True, []
    try:  # the gate's own reading of a running background child, window open or not: a wait, as the gate decides it
        running = _load("stop_command_gate", HOOKS / "stop-command-gate.py").waiting_for(payload) if gated else []
    except Exception:
        running = []
    return window, gated, running


def fallback(raw: bytes, reason: str, limit: float | None = None) -> int:
    if os.environ.get("CLAUDE_COMMAND_GATE", "") == "off":
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    box: list = []  # the record read within READ_LIMIT, else left in a daemon thread
    worker = threading.Thread(target=lambda: box.append(_facts(payload)), daemon=True)
    worker.start()
    worker.join(READ_LIMIT)
    window, gated, running = box[0] if box else (True, True, [])  # not read in time: blocks, nothing verified
    head, tail = _texts(reason, limit)
    if running:
        text = f"{head}; waiting for {', '.join(running)}, still running; not complete\n"
        sys.stderr.write(text)
        sys.stdout.write(json.dumps({"systemMessage": text}) + "\n")
        return 0
    if window or gated:
        failed = "".join(f"; {n}.py could not be loaded ({why})" for n, why in FAILED.items() if n in ("command_span", "overnight"))
        text = head + failed + tail
        sys.stderr.write(text)
        record(raw, __file__, text)
        return 2
    return 0


def record(raw: bytes, hook, text: str) -> None:
    """One line in the refusal record for a blocked stop, written by RECORDER as a process of its own: this file
    loads no harness module for it, and whatever that process does the answer stands."""
    try:
        subprocess.run([sys.executable, str(RECORDER), "refusal", __file__, str(hook), text[:4000].replace("\0", " ")],
                       input=raw, capture_output=True, timeout=RECORD_LIMIT)
    except Exception:
        pass


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
        return fallback(raw, name, COORDINATOR_TIMEOUT)
    except OSError as exc:
        return fallback(raw, f"{name} could not start ({type(exc).__name__})")
    if done.returncode not in (0, 2):
        last = (done.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        return fallback(raw, f"{name} exited {done.returncode}" + (f" ({last})" if last else ""))
    sys.stdout.buffer.write(done.stdout)
    sys.stderr.buffer.write(done.stderr)
    if done.returncode == 2:
        record(raw, HOOKS / name, done.stderr.decode("utf-8", "replace"))
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
