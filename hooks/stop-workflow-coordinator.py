#!/usr/bin/env python3
"""Serialize Stop phases and call the sole receipt-gated resource finalizer.

LANE-B (20260808-035658) M4/M7: registered as the harness's actual Stop hook,
replacing the four discrete phase entries it now sequences internally.

Resource-broker preflight is opt-in, not universal: LANEB_SESSION_RESOURCE_TRUST_KEY
and LANEB_SESSION_RESOURCE_TRUST_ROOT are never set by default anywhere in this
harness (no SessionStart provisioning exists), so nearly every session has no
resource session to finalize. When either trust variable is absent, this
coordinator skips resource preflight/finalize entirely and only runs the four
phases -- it must NOT call session_resources.resolve_current_resource_session()
in that case, because that call unconditionally raises when the trust authority
is unconfigured, which would turn "no LANE-B resource session was ever
provisioned" (the default state for every session) into a permanent stop-block
for the entire harness. Only once a resource session has actually been
provisioned (trust variables present) does resource finalization -- and its
fail-closed guarantees -- apply.
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

from lib import session_resources


PHASE_ORDER = ("timelock", "coverage", "auto_commit", "cleanup")
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


def _default_phases() -> list[Phase]:
    return [
        Phase("timelock", (sys.executable, str(HOOKS / "stop-overnight-timelock.py"))),
        Phase(
            "coverage", (sys.executable, str(HOOKS / "stop-spec-coverage-enforce.py"))
        ),
        Phase("auto_commit", ("bash", str(HOOKS / "auto-commit.sh")), 120.0),
        Phase("cleanup", ("bash", str(HOOKS / "stop-cleanup-allowlist.sh"))),
    ]


def _configured_phases(environment: Mapping[str, str]) -> list[Phase]:
    encoded = environment.get("LANEB_COORDINATOR_PHASES_JSON")
    if not encoded:
        return _default_phases()
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


def _structured_timelock_decision(stdout: str) -> str | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines or lines[-1][0] not in "{[":
        return None
    text = lines[-1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return "invalid"
    if not isinstance(value, dict):
        return "invalid"
    decision = value.get("decision")
    if decision in {"allow", "approve", "pass"}:
        return "allow"
    if decision in {"block", "deny"}:
        return "block"
    return "invalid"


def _run_phase(
    phase: Phase,
    *,
    raw_payload: bytes,
    project_dir: Path,
    phase_environment: Mapping[str, str],
) -> dict:
    child_env = {
        **{
            key: value
            for key, value in phase_environment.items()
            if key not in TRUST_ENVIRONMENT_KEYS
        },
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "LANEB_COORDINATED_STOP": "1",
    }
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
        return {"phase": phase.name, "status": "timeout", "returncode": None}
    except Exception:
        # Phase-launch diagnostics can contain argv/environment data; fail by code only.
        return {"phase": phase.name, "status": "fail", "returncode": None}
    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    status = (
        "allow"
        if result.returncode == 0
        else ("block" if result.returncode == 2 else "fail")
    )
    if phase.name == "timelock" and result.returncode == 0:
        decision = _structured_timelock_decision(stdout)
        if decision in {"invalid", "block"}:
            status = decision
    return {
        "phase": phase.name,
        "status": status,
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }


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
    try:
        selected = (
            list(phases)
            if phases is not None
            else _configured_phases(phase_environment)
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "status": "blocked",
            "reason": "invalid_phase_configuration",
            "phases": [],
            "finalizer_called": False,
        }, 2
    if tuple(phase.name for phase in selected) != PHASE_ORDER:
        return {
            "status": "blocked",
            "reason": "invalid_phase_order",
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
    for phase in selected:
        result = _run_phase(
            phase,
            raw_payload=raw_payload,
            project_dir=root,
            phase_environment=phase_environment,
        )
        results.append(result)
        if result["status"] != "allow":
            return {
                "status": "blocked",
                "reason": f"phase_{result['status']}",
                "failed_phase": phase.name,
                "phases": results,
                "finalizer_called": False,
            }, 2
    if resource_session_id is None:
        # No LANE-B resource session was ever provisioned for this claude
        # session (the default state: nothing opted into scratch/process
        # registration). Phases already ran and passed above; there is
        # nothing to finalize, so this is a normal pass, not a block.
        return {
            "status": "pass",
            "phases": results,
            "finalizer_called": False,
            "reason": "resource_broker_not_configured",
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
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
