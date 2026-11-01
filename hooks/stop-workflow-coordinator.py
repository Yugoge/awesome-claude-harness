#!/usr/bin/env python3
"""Serialize Stop phases and call the sole receipt-gated resource finalizer.

LANE-B (20260808-035658) M4/M7, P5 R9: hooks/stop-launch.py runs it (and a session that
loaded an older hook list runs it directly), running its phases in order: coverage,
auto_commit, completion (hooks/stop-command-gate.py, the one Stop gate), cleanup. A passing
phase may end its stdout with a JSON object whose systemMessage (auto-commit's
refused-snapshot notice) main() shows as this hook's own.

Only coverage and completion may block. A coverage block relays failed_phase=coverage and
the last 4 KB of its stderr; a completion block relays the gate's stderr first (its
`COMMAND_GATE /<command>: not complete` and the gaps), and an allowed completion's stderr
(advisory `would block`) is relayed too. An auto_commit or cleanup failure, and a coverage
failure other than exit 2, is recorded in the result JSON and allowed. A completion
failure (exit outside {0, 2}, timeout, launch error, missing file) is decided by the
stdlib fallback on the transcript reader (`fallback`). Cleanup runs only on an allowed
Stop; a block returns before it. The finalizer runs only when every phase allowed cleanly.

The gate's mode comes from the process environment only (`gate_mode`): CLAUDE_COMMAND_GATE=off
skips completion, and with it the overnight time-lock the gate holds; else the gate blocks when
the launcher ran this coordinator (its LAUNCHER_MARK) and runs advisory when a session that
loaded an older hook list runs it directly (arming option 1).

The terminal receipt (P1b row 15): the gate prints the terminal time-lock status of an
allowed Stop as one stdout line, and this coordinator alone publishes the receipt from it
(session_resources.publish_overnight_receipt), which finalize then reads.

Resource preflight/finalize is opt-in: LANEB_SESSION_RESOURCE_TRUST_KEY and _TRUST_ROOT
are set nowhere by default (no SessionStart provisioning). Without both, only the phases
run and session_resources.resolve_current_resource_session() must NOT be called: it
raises when the trust authority is unconfigured, which would make that default state a
permanent Stop block. Fail-closed finalization applies once a resource session exists.
No phase receives either key.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from lib import command_span, session_resources


PHASE_ORDER = ("coverage", "auto_commit", "completion", "cleanup")
BLOCKING_PHASES = ("coverage", "completion")
STDERR_RELAY_BYTES = 4096
TRUST_ENVIRONMENT_KEYS = (
    session_resources.TRUST_KEY_ENV,
    session_resources.TRUST_ROOT_ENV,
)
FINALIZER_FAILURE_REASONS = frozenset(
    {
        "scratch_symlink_detected",
        "process_identity_mismatch",
        "process_exit_timeout",
    }
)


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


def _environment_views(
    environment: Mapping[str, str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Separate ordinary child state from the two-key trust capability."""

    values = dict(os.environ if environment is None else environment)
    phase_environment = {
        key: value for key, value in values.items() if key not in TRUST_ENVIRONMENT_KEYS
    }
    trust_environment = {key: values.get(key, "") for key in TRUST_ENVIRONMENT_KEYS}
    return phase_environment, trust_environment


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
    try:
        result = subprocess.run(
            list(phase.argv),
            input=raw_payload,
            capture_output=True,
            cwd=str(project_dir),
            env=child_env,
            timeout=phase.timeout,
        )
    except subprocess.TimeoutExpired:
        return {"phase": phase.name, "status": "timeout", "returncode": None, "failure": "timeout"}
    except Exception:
        # Phase-launch diagnostics can contain argv/environment data; fail by code only.
        return {"phase": phase.name, "status": "fail", "returncode": None, "failure": "launch error"}
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
    notice, terminal = last.get("systemMessage"), last.get("timelock_terminal")
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
        **({"_terminal": terminal} if status == "allow" and phase.name == "completion"
           and isinstance(terminal, str) else {}),
        **({"_stderr": relayed} if status == "block" or phase.name == "completion" else {}),
    }


def fallback(payload: Mapping[str, object], mode: str, reason: str) -> tuple[int, str]:
    """A completion that did not decide (exit outside {0, 2}, timeout, launch error,
    missing file), decided on the transcript reader alone: block while the session's
    overnight window is open (overnight.window_open) or, in block mode, while the latest
    human-typed command is a gated one; else allow. The reader reads the whole transcript:
    an opener may lie far back. A check whose module cannot load counts as not holding."""
    try:
        from lib import overnight

        window = bool(overnight.window_open(dict(payload)))
    except Exception:
        window = False
    gated = mode == "block" and (
        command_span.active_command(payload.get("transcript_path")) in command_span.GATED_COMMANDS
    )
    if window or gated:
        return 2, (
            f"COMMAND_GATE instrument failure: {reason}. The gate is broken; "
            "the human can type /stop\n"
        )
    return 0, ""


def _publish_receipt(root: Path, session_id: str, terminal: str, payload: Mapping[str, object]) -> str | None:
    """The terminal receipt finalize reads (P1b row 15), published from the gate's terminal
    time-lock status; None, else the reason it was not published (recorded, allowed)."""
    try:
        from lib import overnight

        _state_file, state = overnight.session_state_file(  # as the gate's time-lock found it
            session_id, (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd") or str(root))
        )
        if state is None:
            return "no overnight state record"
        result = session_resources.publish_overnight_receipt(
            root, claude_session_id=session_id, state=state, terminal_status=terminal
        )
    except Exception as exc:  # recorded by type only: trust diagnostics never cross hook output
        return f"receipt not published ({type(exc).__name__})"
    return None if isinstance(result, Mapping) and result.get("status") == "pass" else "receipt not published"


def run_coordinator(
    payload: Mapping[str, object],
    *,
    raw_payload: bytes | None = None,
    project_dir: Path | str | None = None,
    environment: Mapping[str, str] | None = None,
    phases: Sequence[Phase] | None = None,
) -> tuple[dict, int]:
    """Run phases sequentially; every non-success is non-destructive."""

    phase_environment, trust_environment = _environment_views(environment)
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
            "reason": "subagent_stop_never_finalizes_parent_resources",
            "phases": [],
            "finalizer_called": False,
        }, 0
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return {
            "status": "nonterminal",
            "reason": "missing_parent_session_id",
            "phases": [],
            "finalizer_called": False,
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
            "finalizer_called": False,
        }, 2
    resource_broker_configured = bool(trust_environment.get(session_resources.TRUST_KEY_ENV)) and bool(
        trust_environment.get(session_resources.TRUST_ROOT_ENV)
    )
    resource_session_id: str | None = None
    if resource_broker_configured:
        try:
            pointer = session_resources.resolve_current_resource_session(
                root,
                session_id,
                trust_environment=trust_environment,
            )
            if not isinstance(pointer, Mapping):
                raise ValueError("invalid resource preflight result")
            resource_session_id = pointer.get("resource_session_id")
            if not isinstance(resource_session_id, str) or not resource_session_id:
                raise ValueError("invalid resource preflight identity")
        except Exception:
            # Trust-provider diagnostics are capabilities and never cross hook output.
            return {
                "status": "blocked",
                "reason": "resource_preflight_contract_error",
                "phases": [],
                "finalizer_called": False,
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
        terminal = result.pop("_terminal", None)
        if phase.name == "completion" and result["status"] in ("allow", "block") and stderr:
            relays.append(stderr)
        if terminal and resource_session_id is not None:  # finalize decides on the receipt
            receipt = _publish_receipt(root, session_id, terminal, payload)
            if receipt:
                result["receipt"] = receipt
        if result["status"] == "allow":
            continue
        if result["status"] == "block" and phase.name in BLOCKING_PHASES:
            return {
                "status": "blocked",
                "reason": "phase_block",
                "failed_phase": phase.name,
                "phases": results,
                "finalizer_called": False,
                "_relay": "".join(relays) if phase.name == "completion" else f"failed_phase={phase.name}\n{stderr}",
            }, 2
        if phase.name != "completion":
            continue  # recorded in the result and allowed
        code, relay = fallback(payload, mode, result["failure"])
        result["fallback"] = "block" if code == 2 else "allow"
        if code != 2:
            continue  # recorded in the result and allowed
        return {
            "status": "blocked",
            "reason": "completion_instrument_failure",
            "failed_phase": phase.name,
            "phases": results,
            "finalizer_called": False,
            "_relay": relay,
        }, 2
    advisory = "".join(relays)
    if any(result["status"] not in ("allow", "skipped") for result in results):
        # A recorded failure is allowed but never followed by the destructive finalizer.
        return {
            "status": "pass",
            "phases": results,
            "finalizer_called": False,
            "reason": "phase_failure_recorded",
            **({"_relay": advisory} if advisory else {}),
        }, 0
    if resource_session_id is None:
        # No resource session was provisioned (the default): the phases passed and
        # there is nothing to finalize, so this is a normal pass, not a block.
        return {
            "status": "pass",
            "phases": results,
            "finalizer_called": False,
            "reason": "resource_broker_not_configured",
            **({"_relay": advisory} if advisory else {}),
        }, 0
    try:
        finalized = session_resources.finalize(
            root,
            claude_session_id=session_id,
            resource_session_id=resource_session_id,
            trust_environment=trust_environment,
        )
    except Exception:
        # Finalizer diagnostics may name trusted paths; expose only a fixed code.
        return {
            "status": "blocked",
            "reason": "resource_finalizer_contract_error",
            "phases": results,
            "finalizer_called": True,
        }, 2
    if not isinstance(finalized, Mapping) or finalized.get("status") != "pass":
        error_code = (
            finalized.get("error_code") if isinstance(finalized, Mapping) else None
        )
        reason = (
            error_code
            if error_code in FINALIZER_FAILURE_REASONS
            else "resource_finalize_failed"
        )
        return {
            "status": "blocked",
            "reason": reason,
            "phases": results,
            "finalizer_called": True,
        }, 2
    return {
        "status": "pass",
        "phases": results,
        "finalizer_called": True,
        "resource_session_id": resource_session_id,
        "finalizer": finalized,
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
