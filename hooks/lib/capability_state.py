#!/usr/bin/env python3
"""Capability-handshake trust root: canonical binding, state provenance, aggregate
verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer.

This module is a plain importable library, never a hook. That is load-bearing:
the PreToolUse capability gate is delivered by the very mechanism it polices, so a
host that silently no-ops PreToolUse also no-ops the gate. Every enforcement
decision here is reachable in-process from a protected workflow's own entrypoint
and from `scripts/doctor --strict`, with no hook dispatch involved.

Deliberate structural property (do not "optimise" it away): the consumer NEVER
parses the `hooks` arrays of any settings layer. Settings files are read as raw
BYTES for hashing only. A consumer that inspected gate registration could defer
whenever the gate looks registered and would deliver zero protection on the real
threat host -- one that lists the gate in settings.json and never dispatches it.

Normalisation notes (stated rather than implied):
  - harness_version is the VERSION file's content with surrounding whitespace
    stripped (so it equals `$(cat VERSION)` as a shell comparison would produce).
  - host_build is the leading version token of `claude --version`, the single
    named authoritative source. Empty / missing / "unknown" is non-passing.

Exit codes: n/a (library).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST_RELPATH = "policies/protected-workflow-manifest.v1.json"
VERSION_RELPATH = "VERSION"

# Fixed order is part of the canonical binding definition -- reordering changes
# the tuple and is therefore a breaking change, not a refactor.
SETTINGS_LAYERS = ("settings.json", "settings.local.json", ".claude/settings.local.json")

RELIED_UPON_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SubagentStop",
)

# host_receipt fields, tiered per the ticket's Evidence table. Tier-3 fields are
# RECORDED IF PRESENT and explicitly marked absent otherwise -- never silently
# omitted, and never asserted upon.
RECEIPT_CORE_FIELDS = ("session_id", "transcript_path", "cwd")
RECEIPT_TIER3_FIELDS = ("hook_event_name", "permission_mode")
ABSENT = "absent"

DEEP_CHECKS = (
    "identity_propagation",
    "permission_deny",
    "hook_ordering",
    "model_invocation_restriction",
)
ORDERING_PROPERTIES = (
    "cross_event_ordering",
    "startup_barrier",
    "sibling_completion_barrier",
    "blocking_precedence",
    "declared_order_and_exit2_short_circuit",
)

PENDING_TIMEOUT_SEC = 900
NONCE_BITS = 128


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def harness_home(explicit: str | os.PathLike | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env).resolve()
    # <home>/hooks/lib/capability_state.py -> <home>
    return Path(__file__).resolve().parent.parent.parent


def state_dir() -> Path:
    """Owner-controlled runtime directory, created 0700."""
    override = os.environ.get("CLAUDE_CAPABILITY_STATE_DIR")
    if override:
        d = Path(override)
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        d = Path(xdg) / "claude-capability" if xdg else Path(f"/tmp/claude-capability-{os.geteuid()}")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def state_path(session_id: str, directory: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "unknown-session")
    return (directory or state_dir()) / f"capability-handshake-{safe}.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_nonce() -> str:
    return secrets.token_hex(NONCE_BITS // 8)


# --------------------------------------------------------------------------- #
# canonical binding (AC-CAPGATE-03)
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def settings_records(home: Path) -> list[dict]:
    """Fixed-order, path-tagged SHA-256 records for the three settings layers.

    An unreadable-but-present layer yields present=True with sha256=None, which
    binding_failure() treats as fail-closed. Reading is byte-level only: this
    function must never parse hook arrays (see module docstring).
    """
    out: list[dict] = []
    for rel in SETTINGS_LAYERS:
        p = home / rel
        rec: dict = {"path": rel, "present": False, "sha256": None}
        if p.is_file():
            rec["present"] = True
            try:
                rec["sha256"] = sha256_bytes(p.read_bytes())
            except OSError:
                rec["sha256"] = None
        out.append(rec)
    return out


def read_harness_version(home: Path) -> str | None:
    try:
        return (home / VERSION_RELPATH).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def read_host_build() -> str | None:
    """Single named authoritative source: `claude --version`."""
    try:
        r = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"\d+\.\d+\.\d+[A-Za-z0-9.+-]*", r.stdout or "")
    return m.group(0) if m else None


def canonical_binding(home: Path | None = None) -> dict:
    h = harness_home(home)
    return {
        "settings_records": settings_records(h),
        "harness_version": read_harness_version(h),
        "host_build": read_host_build(),
    }


def binding_failure(binding: dict) -> str | None:
    """None when the binding is self-consistent and passable; else a reason."""
    recs = binding.get("settings_records")
    if not isinstance(recs, list) or len(recs) != len(SETTINGS_LAYERS):
        return "binding_records_malformed"
    for rec, rel in zip(recs, SETTINGS_LAYERS):
        if not isinstance(rec, dict) or rec.get("path") != rel:
            return "binding_records_malformed"
        if rec.get("present") and not rec.get("sha256"):
            return "binding_layer_unreadable"
    hv = binding.get("harness_version")
    hb = binding.get("host_build")
    if not hv:
        return "binding_harness_version_missing"
    if not hb or str(hb).strip().lower() == "unknown":
        return "binding_host_build_unknown"
    return None


def binding_matches(stored: dict, recomputed: dict) -> bool:
    """Byte-exact tuple equality. Installer-originated writes are NOT special-cased:
    a render-settings run that alters settings.json bytes invalidates exactly as a
    hand-edit does, because only the resulting bytes are ever compared."""
    return json.dumps(stored, sort_keys=True) == json.dumps(recomputed, sort_keys=True)


# --------------------------------------------------------------------------- #
# state file: atomic write + provenance validation (AC-CAPGATE-09)
# --------------------------------------------------------------------------- #
def write_state_atomic(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".caphs.", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_REQUIRED_STATE_KEYS = (
    "schema_version",
    "status",
    "session_id",
    "run_id",
    "nonce",
    "start_time",
    "binding",
    "events",
    "deep_checks",
)


def load_state(path: Path, expected_session_id: str | None = None, now: float | None = None):
    """Return (state|None, failure_reason|None). Fail-closed on every anomaly."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, "state_absent"
    except OSError:
        return None, "state_unreadable"

    if stat.S_ISLNK(st.st_mode):
        return None, "state_symlink"
    if st.st_uid != os.geteuid():
        return None, "state_wrong_owner"
    if stat.S_IMODE(st.st_mode) & 0o077:
        return None, "state_insecure_mode"

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "state_malformed"
    if not isinstance(state, dict):
        return None, "state_malformed"
    if state.get("schema_version") != SCHEMA_VERSION:
        return None, "state_schema_version_mismatch"
    missing = [k for k in _REQUIRED_STATE_KEYS if k not in state]
    if missing:
        # This is the branch a hand-written {"status":"PASS"} lands in.
        return None, "state_partial"
    if expected_session_id and state.get("session_id") != expected_session_id:
        return None, "state_wrong_session"
    if state.get("status") == "PENDING":
        started = _epoch(state.get("start_time"))
        ref = time.time() if now is None else now
        if started is None or (ref - started) > PENDING_TIMEOUT_SEC:
            return None, "state_pending_timeout"
    return state, None


def _epoch(iso: str | None) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# aggregate PASS formula (AC-CAPGATE-04)
# --------------------------------------------------------------------------- #
def aggregate_verdict(state: dict, home: Path | None = None) -> tuple[str, str | None]:
    """Return (overall, failure_reason). overall is 'PASS' or 'UNPROTECTED'.

    Every failure class carries a DISTINGUISHABLE reason so a negative test can
    prove which mechanism fired (AC-CAPGATE-01 requires this explicitly).
    """
    if state.get("status") == "PENDING":
        return "UNPROTECTED", "state_pending"
    if state.get("status") != "PASS":
        return "UNPROTECTED", f"state_status_{str(state.get('status')).lower()}"

    stored = state.get("binding") or {}
    reason = binding_failure(stored)
    if reason:
        return "UNPROTECTED", reason
    if not binding_matches(stored, canonical_binding(home)):
        return "UNPROTECTED", "binding_mismatch"

    events = state.get("events")
    if not isinstance(events, list):
        return "UNPROTECTED", "missing_event_record"
    by_label = {e.get("event_label"): e for e in events if isinstance(e, dict)}
    for label in RELIED_UPON_EVENTS:
        if label not in by_label:
            return "UNPROTECTED", "missing_event_record"
    run_id = state.get("run_id")
    seen_nonces: set[str] = set()
    for label in RELIED_UPON_EVENTS:
        ev = by_label[label]
        if ev.get("run_id") != run_id:
            return "UNPROTECTED", "receipt_run_id_mismatch"
        ev_nonce = ev.get("nonce")
        if not ev_nonce:
            return "UNPROTECTED", "receipt_nonce_missing"
        # Per-event-DISTINCT, run-bound nonces: a replayed or shared nonce cannot
        # evidence that this receipt came from THIS event's registration.
        if ev_nonce in seen_nonces:
            return "UNPROTECTED", "receipt_nonce_not_event_distinct"
        seen_nonces.add(ev_nonce)
        if ev.get("event_discriminator") == "unsupported_self_check":
            return "UNPROTECTED", "event_identity_unsupported"
        if ev.get("outcome") != "PASS":
            return "UNPROTECTED", "event_probe_failed"
        receipt = ev.get("host_receipt") or {}
        for f in RECEIPT_CORE_FIELDS:
            if not receipt.get(f):
                return "UNPROTECTED", "host_receipt_core_field_missing"
        for f in RECEIPT_TIER3_FIELDS:
            if f not in receipt:
                return "UNPROTECTED", "host_receipt_tier3_field_omitted"
        if ev.get("blocking_action") == "FAIL":
            return "UNPROTECTED", "blocking_check_failed"

    deep = state.get("deep_checks") or {}
    for name in DEEP_CHECKS:
        rec = deep.get(name)
        if not isinstance(rec, dict):
            return "UNPROTECTED", "deep_check_missing"
        if rec.get("status") == "unsupported_self_check":
            return "UNPROTECTED", "deep_check_unsupported"
        if rec.get("status") != "pass":
            return "UNPROTECTED", "deep_check_failed"
    ordering = (deep.get("hook_ordering") or {}).get("properties") or {}
    for prop in ORDERING_PROPERTIES:
        p = ordering.get(prop)
        if not isinstance(p, dict):
            return "UNPROTECTED", "ordering_property_omitted"
        if p.get("status") == "unsupported_self_check":
            return "UNPROTECTED", "deep_check_unsupported"
        if p.get("status") != "pass":
            return "UNPROTECTED", "deep_check_failed"

    surface = state.get("status_surface") or {}
    if surface.get("status") != "observed":
        return "UNPROTECTED", "status_surface_unobservable"
    return "PASS", None


# --------------------------------------------------------------------------- #
# protected-workflow manifest (AC-CAPGATE-08)
# --------------------------------------------------------------------------- #
def load_manifest(home: Path | None = None, path: Path | None = None) -> tuple[dict | None, str | None]:
    p = Path(path) if path else harness_home(home) / MANIFEST_RELPATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "manifest_unreadable"
    if not isinstance(data, dict) or not isinstance(data.get("routes"), list):
        return None, "manifest_malformed"
    return data, None


def classify_route(tool_name: str, tool_input: dict | None) -> str:
    """Map a tool-call envelope onto a manifest route key."""
    ti = tool_input or {}
    if tool_name == "SlashCommand":
        cmd = str(ti.get("command") or "").strip().split()[0:1]
        return f"slashcommand:{cmd[0]}" if cmd else "slashcommand:"
    if tool_name == "Skill":
        return f"skill:{str(ti.get('skill') or ti.get('name') or '').strip()}"
    return f"tool:{tool_name}"


def route_lookup(manifest: dict, route: str) -> tuple[dict | None, bool]:
    """Return (entry|None, in_protected_surface).

    The protected SURFACE is the set of route CLASSES this handshake gates. A
    route inside the surface but absent from routes[] is fail-closed (blocked)
    per AC-CAPGATE-08. A route outside the surface is not this gate's business
    and is reported not_protected -- deliberately, so the gate cannot brick
    ordinary tool use it was never meant to police.
    """
    for entry in manifest.get("routes", []):
        if isinstance(entry, dict) and entry.get("route") == route:
            return entry, True
    prefixes = manifest.get("protected_surface_prefixes") or []
    return None, any(route.startswith(p) for p in prefixes)


# --------------------------------------------------------------------------- #
# INDEPENDENT preactivation consumer (AC-CAPGATE-10)
# --------------------------------------------------------------------------- #
def _state_digest(path: Path) -> str | None:
    try:
        return "sha256:" + sha256_bytes(path.read_bytes())
    except OSError:
        return None


def evaluate_activation(
    route: str,
    *,
    home: Path | None = None,
    session_id: str | None = None,
    state_file: Path | None = None,
    manifest_path: Path | None = None,
    component: str = "independent_consumer",
    now: float | None = None,
) -> dict:
    """Decide whether a protected-workflow activation may proceed.

    Reads ONLY: the manifest, the state file, and the settings layers' raw bytes
    (for the binding recompute). It never inspects hook registration, so its
    decision is a pure function of handshake state -- which is what makes the
    (gate REMOVED, PASS) cell PERMIT and the (gate REMOVED, non-PASS) cell REFUSE.

    Returns a decision record naming the exact state input consulted, per the
    input-attribution corollary. Acceptance/runtime trust evidence only; this is
    not a public logging or audit interface.
    """
    sid = session_id or os.environ.get("CLAUDE_SESSION_ID") or ""
    sp = Path(state_file) if state_file else state_path(sid)
    record = {
        "component": component,
        "route": route,
        "decision": "REFUSE",
        "failure_reason": None,
        "state_input": {"path": str(sp), "digest": _state_digest(sp), "run_id": None, "nonce": None},
        "manifest_version": None,
        "timestamp": now_iso(),
    }

    manifest, merr = load_manifest(home, manifest_path)
    if merr:
        record["failure_reason"] = f"{component}_refused: {merr}"
        return record
    record["manifest_version"] = manifest.get("manifest_version")

    entry, in_surface = route_lookup(manifest, route)
    if entry is None:
        record["failure_reason"] = (
            f"{component}_refused: unmanifested_route"
            if in_surface
            else f"{component}_not_applicable: route_outside_protected_surface"
        )
        record["decision"] = "REFUSE" if in_surface else "NOT_PROTECTED"
        return record
    if not entry.get("independent_enforcement", False):
        record["decision"] = "REFUSE"
        record["failure_reason"] = f"{component}_refused: route_unsupported_no_independent_enforcement"
        return record

    state, serr = load_state(sp, expected_session_id=sid or None, now=now)
    if serr:
        record["failure_reason"] = f"{component}_refused: state={serr}"
        return record
    record["state_input"]["run_id"] = state.get("run_id")
    record["state_input"]["nonce"] = state.get("nonce")

    overall, reason = aggregate_verdict(state, home)
    if overall != "PASS":
        record["failure_reason"] = f"{component}_refused: state={reason}"
        return record
    record["decision"] = "PERMIT"
    return record


def activation_eligible(state: dict | None, home: Path | None = None) -> bool:
    if not isinstance(state, dict):
        return False
    return aggregate_verdict(state, home)[0] == "PASS"
