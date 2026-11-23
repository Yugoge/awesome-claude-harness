#!/usr/bin/env python3
"""Serialize Stop phases.

LANE-B (20260808-035658) M4/M7, P5 R9: run by hooks/stop-launch.py (directly by a session that
loaded an older hook list), in order: coverage, auto_commit, completion (hooks/stop-command-gate.py,
the one Stop gate), cleanup. A passing phase may end its stdout with a JSON object whose
systemMessage (auto-commit's refused-snapshot notice) main() shows as this hook's own.

Only coverage and completion block: a coverage block relays failed_phase=coverage and the last
4 KB of its stderr, completion's stderr (its block text, or advisory `would block`) is relayed
whole and first. Other failures are recorded in the result JSON and allowed; a completion that did
not decide (exit outside {0, 2}, timeout, launch error, missing file) goes to `fallback`. Cleanup
runs only on an allowed Stop. `gate_mode` reads the process environment only. Each phase runs in
a process group of its own; one out of time is ended with its whole group (`_end_group`), so
`worst_case_seconds` (each limit plus KILL_GRACE, plus the fallback's FALLBACK_LIMIT) bounds the
coordinator under the launcher's limit. The fallback reads a running background child as the gate
and the launcher do (the gate's waiting_for): a wait, exit 0, its text relayed and shown.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from lib import command_span


PHASE_ORDER = ("coverage", "auto_commit", "completion", "cleanup")
BLOCKING_PHASES = ("coverage", "completion")
STDERR_RELAY_BYTES = 4096
KILL_GRACE = 5.0  # what ending a phase out of time may cost (_end_group)
FALLBACK_LIMIT = 10.0  # what fallback's reading of the session record may cost (_bounded)


@dataclass(frozen=True)
class Phase:
    name: str
    argv: tuple[str, ...]
    timeout: float = 30.0


# hooks/stop-launch.py sets it for the coordinator it runs (arming option 1, P5 "Arming").
LAUNCHER_MARK = "CLAUDE_STOP_LAUNCHER"


def gate_mode(environment: Mapping[str, str]) -> str:
    """The Stop gate's mode, from the process environment only: CLAUDE_COMMAND_GATE=off is
    off; any other value, or none, blocks (P5-d) when the launcher ran this coordinator. A
    session that loaded an older hook list runs it directly, unmarked: completion runs
    advisory there and the time-lock still blocks; a forged mark only arms."""
    if environment.get("CLAUDE_COMMAND_GATE", "") == "off":
        return "off"
    return "block" if environment.get(LAUNCHER_MARK) == "1" else "advisory"


def _default_phases(mode: str = "block") -> list[Phase]:
    return [
        Phase(
            "coverage", (sys.executable, str(HOOKS / "stop-spec-coverage-enforce.py"))
        ),
        Phase("auto_commit", ("bash", str(HOOKS / "auto-commit.sh")), 120.0),
        Phase("completion", (sys.executable, str(HOOKS / "stop-command-gate.py"), "--mode", mode), 60.0),
        Phase("cleanup", ("bash", str(HOOKS / "stop-cleanup-allowlist.sh"))),
    ]


def _configured_phases(environment: Mapping[str, str], mode: str) -> list[Phase]:
    encoded = environment.get("LANEB_COORDINATOR_PHASES_JSON")
    if not encoded:
        return _default_phases(mode)
    value = json.loads(encoded)
    if not isinstance(value, list) or len(value) != len(PHASE_ORDER):
        raise ValueError("phase configuration must define the four exact phases")
    phases = []
    for expected, item in zip(PHASE_ORDER, value):
        if not isinstance(item, dict) or item.get("name") != expected:
            raise ValueError("phase order mismatch")
        argv = item.get("argv")
        timeout = item.get("timeout", 30.0)
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(part, str) and part for part in argv)
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError(f"invalid phase configuration: {expected}")
        phases.append(Phase(expected, tuple(argv), float(timeout)))
    return phases


def worst_case_seconds(phases: Sequence[Phase]) -> float:
    """The longest the phases can take: each runs to its limit and is then ended (KILL_GRACE),
    and a completion with no verdict is decided by `fallback` within FALLBACK_LIMIT."""
    return sum(phase.timeout + KILL_GRACE for phase in phases) + FALLBACK_LIMIT


def _end_group(proc: subprocess.Popen) -> None:
    """End a phase out of time with its whole process group (SIGKILL), then reap it: its pipes
    close once every process of the group has died. A process that left the group (a session of
    its own) and still holds a pipe is waited for no longer than KILL_GRACE."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.communicate(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        for stream in (proc.stdout, proc.stderr):
            stream.close()
        proc.wait()


def _phase_script(argv: Sequence[str]) -> str | None:
    """The script a phase runs: its first argument after the interpreter that
    names a .py or .sh file (python3 on a missing file exits 2, a block)."""
    return next((part for part in argv[1:] if part.endswith((".py", ".sh"))), None)


def _run_phase(
    phase: Phase,
    *,
    raw_payload: bytes,
    project_dir: Path,
    phase_environment: Mapping[str, str],
) -> dict:
    child_env = {
        **phase_environment,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "LANEB_COORDINATED_STOP": "1",
    }
    script = _phase_script(phase.argv)
    if script is not None and not Path(script).is_file():
        return {"phase": phase.name, "status": "fail", "returncode": None, "failure": "missing file"}
    try:  # its own process group, so a phase out of time ends with everything it started
        proc = subprocess.Popen(list(phase.argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=str(project_dir), env=child_env,
                                start_new_session=True)  # process_group needs 3.11; CI runs 3.10
    except Exception:
        # Phase-launch diagnostics can contain argv/environment data; fail by code only.
        return {"phase": phase.name, "status": "fail", "returncode": None, "failure": "launch error"}
    try:
        out, err = proc.communicate(raw_payload, timeout=phase.timeout)
    except subprocess.TimeoutExpired:
        _end_group(proc)
        return {"phase": phase.name, "status": "timeout", "returncode": None, "failure": "timeout",
                "limit": phase.timeout}
    result = subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    status = (
        "allow"
        if result.returncode == 0
        else ("block" if result.returncode == 2 else "fail")
    )
    try:  # the last stdout line: a notice (module docstring), or the gate's terminal status
        last = json.loads(stdout.strip().splitlines()[-1])
    except (LookupError, TypeError, ValueError):
        last = {}
    last = last if isinstance(last, dict) else {}
    notice = last.get("systemMessage")
    failure = {"fail": f"exit code {result.returncode}"}.get(status)
    # The gate's own text is relayed whole and first (P5 R9); a coverage block's last 4 KB.
    relayed = stderr if phase.name == "completion" else stderr[-STDERR_RELAY_BYTES:]
    return {
        "phase": phase.name,
        "status": status,
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        **({"failure": failure} if failure else {}),
        **({"notice": notice} if status == "allow" and isinstance(notice, str) else {}),
        **({"_stderr": relayed} if status == "block" or phase.name == "completion" else {}),
    }


def _holds(check) -> bool:
    try:
        return bool(check())
    except Exception:
        return False


def _record(payload: Mapping[str, object], mode: str) -> tuple[bool, bool, list[str]]:
    """(overnight window open, latest human-typed command gated in block mode, its running background
    children as the gate reads them: stop-command-gate.py's waiting_for, the one reading of the wait)."""
    def window() -> bool:
        from lib import overnight
        return overnight.window_open(dict(payload))

    def latest_command():  # read from what the Stop gate's index keeps of the conversation, not the whole of it again
        from lib import locations
        return command_span.active_command(payload.get("transcript_path"), keep=locations.state_root())

    gated = mode == "block" and _holds(lambda: latest_command() in command_span.GATED_COMMANDS)
    try:
        spec = importlib.util.spec_from_file_location("stop_command_gate", HOOKS / "stop-command-gate.py")
        gate = sys.modules["stop_command_gate"] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        running = list(gate.waiting_for(dict(payload))) if gated else []
    except Exception:
        running = []
    return _holds(window), gated, running


def _bounded(read, limit: float):
    """read()'s value, or None when it has not returned within ``limit`` s (it is left in a daemon thread)."""
    box: list = []
    worker = threading.Thread(target=lambda: box.append(read()), daemon=True)
    worker.start()
    worker.join(limit)
    return box[0] if box else None


def no_verdict_text(subject: str, limit: float) -> tuple[str, str]:
    """(head, tail) of the text for ``subject`` out of time after ``limit`` s; hooks/stop-launch.py says the same."""
    return (f"COMMAND_GATE: {subject} ran out of time after {limit:g} s and has no verdict",
            ", so this stop is not let through as complete. The gate keeps what it computed, so the next stop "
            "continues from there. The owner can end the command with /stop.\n")


def fallback(payload: Mapping[str, object], mode: str, reason: str,
             limit: float | None = None) -> tuple[int, str]:
    """A completion that did not decide (exit outside {0, 2}, timeout, launch error,
    missing file), decided on the session record alone (_record, read within FALLBACK_LIMIT):
    a running background child of a gated span is a wait (exit 0, its text shown); else
    block while the session's overnight window is open or, in block mode, while the latest
    human-typed command is a gated one; else allow. A record not read in time blocks, saying
    so. The reader reads the whole transcript: an opener may lie far back. A check whose
    module cannot load counts as not holding. A gate out of time (``limit`` its seconds) is
    said to have no verdict, naming /stop and that the next stop continues its work."""
    head, tail = (no_verdict_text("the gate", limit) if reason == "timeout" and limit is not None else
                  (f"COMMAND_GATE instrument failure: {reason}", ". The gate is broken; the human can type /stop\n"))
    facts = _bounded(lambda: _record(payload, mode), FALLBACK_LIMIT)
    if facts is None:
        return 2, f"{head}; the session record was not read within {FALLBACK_LIMIT:g} s{tail}"
    window, gated, running = facts
    if running:
        return 0, f"{head}; waiting for {', '.join(running)}, still running; not complete\n"
    if not (window or gated):
        return 0, ""
    return 2, head + tail


def run_coordinator(
    payload: Mapping[str, object],
    *,
    raw_payload: bytes | None = None,
    project_dir: Path | str | None = None,
    environment: Mapping[str, str] | None = None,
    phases: Sequence[Phase] | None = None,
) -> tuple[dict, int]:
    """Run phases sequentially; every non-success is non-destructive."""

    phase_environment = dict(os.environ if environment is None else environment)
    root_value = (
        project_dir
        or phase_environment.get("CLAUDE_PROJECT_DIR")
        or payload.get("cwd")
        or os.getcwd()
    )
    if not isinstance(root_value, (str, os.PathLike)):
        root_value = os.getcwd()
    root = Path(root_value)
    if payload.get("agent_id"):
        return {
            "status": "nonterminal",
            "reason": "subagent_stop_runs_no_phase",
            "phases": [],
        }, 0
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return {
            "status": "nonterminal",
            "reason": "missing_parent_session_id",
            "phases": [],
        }, 0
    if raw_payload is None:
        raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    mode = gate_mode(phase_environment)
    try:
        selected = (
            list(phases)
            if phases is not None
            else _configured_phases(phase_environment, mode)
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "status": "blocked",
            "reason": "invalid_phase_configuration",
            "phases": [],
        }, 2
    results = []
    relays = []
    for phase in selected:
        if phase.name == "completion" and mode == "off":
            results.append({"phase": phase.name, "status": "skipped", "returncode": None,
                            "reason": "CLAUDE_COMMAND_GATE=off"})
            continue
        result = _run_phase(
            phase,
            raw_payload=raw_payload,
            project_dir=root,
            phase_environment=phase_environment,
        )
        results.append(result)
        stderr = result.pop("_stderr", "")
        if phase.name == "completion" and result["status"] in ("allow", "block") and stderr:
            relays.append(stderr)
        if result["status"] == "allow":
            continue
        if result["status"] == "block" and phase.name in BLOCKING_PHASES:
            return {
                "status": "blocked",
                "reason": "phase_block",
                "failed_phase": phase.name,
                "phases": results,
                "_relay": "".join(relays) if phase.name == "completion" else f"failed_phase={phase.name}\n{stderr}",
            }, result["returncode"]  # the phase's own exit (2), relayed as stop-launch.py relays its child
        if phase.name != "completion":
            continue  # recorded in the result and allowed
        code, relay = fallback(payload, mode, result["failure"], result.get("limit"))
        result["fallback"] = "block" if code == 2 else ("wait" if relay else "allow")
        if code != 2:
            if relay:  # the wait: relayed and shown to the owner as the gate's own wait is
                relays.append(relay)
                result["notice"] = relay
            continue  # recorded in the result and allowed
        return {
            "status": "blocked",
            "reason": "completion_instrument_failure",
            "failed_phase": phase.name,
            "phases": results,
            "_relay": relay,
        }, 2
    advisory = "".join(relays)
    recorded = any(result["status"] not in ("allow", "skipped") for result in results)
    return {
        "status": "pass",
        "phases": results,
        **({"reason": "phase_failure_recorded"} if recorded else {}),
        **({"_relay": advisory} if advisory else {}),
    }, 0


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    result, exit_code = run_coordinator(payload, raw_payload=raw or b"{}")
    relay = result.pop("_relay", "")
    if relay:
        sys.stderr.write(relay)
    notices = [phase.pop("notice") for phase in result["phases"] if "notice" in phase]
    if notices:
        result["systemMessage"] = "\n".join(notices)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
