#!/usr/bin/env python3
"""Capability-handshake trust root: canonical binding, state provenance, aggregate
verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer.

This module is a plain importable library, never a hook. That is load-bearing:
the PreToolUse capability gate is delivered by the very mechanism it polices, so a
host that silently no-ops PreToolUse also no-ops the gate.

`evaluate_activation()` is the non-circular enforcement point. Its callsites are
named here rather than implied, because a docstring that named entrypoints which
never call it is how the "independent" half of this design came to be decorative:

  - `scripts/capability-doctor-strict.py --route <route>`  -- the per-route
    preflight a protected workflow invokes before it activates. This is the
    supported entrypoint-side callsite and the value of the manifest's
    `independent_enforcement_callsite` field.
  - `scripts/capability-doctor-strict.py` (and therefore `scripts/doctor
    --strict`) -- sweeps every manifested route in one pass.
  - `hooks/pretool-capability-gate.py` -- defense-in-depth only, and the one
    caller that IS hook-dispatched.

None of the first two involve hook dispatch, so they still refuse on a host that
silently no-ops PreToolUse. What is NOT yet true, and is tracked as an open
residual rather than asserted here: no `commands/*.md` entrypoint invokes the
preflight yet, because a blocking preflight cannot be landed until the handshake
can actually reach PASS on a live host.

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

# The human consent escape hatches, duplicated here as a constant so the recovery
# path survives an unreadable or malformed manifest. Refusing these two routes
# because the manifest is broken is precisely the self-sealing failure this
# carve-out exists to prevent. A drift test pins this tuple to the manifest's
# `human_consent_escape_hatch` flags and to the gate hook's own literal.
HUMAN_CONSENT_ESCAPE_HATCH_ROUTES = ("slashcommand:/do", "slashcommand:/allow")

# THE REPAIR FLOOR. A CLOSED, exactly-enumerated set of routes that stay usable
# in every degraded state, so a human (or an agent acting for one) can always
# read, modify and execute the artifacts whose corruption produced that state.
#
# It is manifest-INDEPENDENT on purpose: the manifest is one of the artifacts a
# degraded state implies is unreadable, so a floor derived from it would live
# inside its own failure domain. The gate hook carries a second copy as a
# pre-import literal for the same reason -- this module is itself a
# BOUND_ARTIFACTS member, so a floor declared only here cannot help when THIS
# file is what failed to load. A drift test pins the two copies equal.
#
# CLOSED means closed: the set is asserted by EQUALITY, not membership, so
# adding or removing a route fails a test. Disjointness from the protected
# surface does NOT bound this set -- the surface is entirely `slashcommand:` and
# `skill:` while every member here is `tool:`, so disjointness holds for ANY
# subset of the tool namespace and would wave through a namespace-wide
# fail-open. Equality is the only guard. Widening this set because some other
# tool refused during a repair is the defect, not the fix.
REPAIR_FLOOR_ROUTES = (
    "tool:Read",
    "tool:Edit",
    "tool:Write",
    "tool:Bash",
    "tool:Glob",
    "tool:Grep",
)

# Per-member security rationale, recorded as data so a test can assert that no
# member was admitted without one. Every member is PERMANENTLY outside the
# protected surface, which is why each has to earn its place.
REPAIR_FLOOR_RATIONALE = {
    "tool:Read": "Inspect the corrupt artifact. Read-only; cannot mutate the protected surface.",
    "tool:Edit": "Surgically repair a partially-corrupt artifact. Mutating, and the accepted "
                 "minimum: a repair path that cannot write is not a repair path.",
    "tool:Write": "Replace an artifact too corrupt to patch. Strictly necessary for the "
                  "malformed-manifest state, where Edit has no anchor to match.",
    "tool:Bash": "Execute the validator that confirms the repair, or restore from version "
                 "control. The highest-value route to an attacker and the uncomfortable "
                 "member -- accepted because in a degraded state the gate holds no manifest "
                 "and is enforcing nothing at all, so refusing Bash prevents repair without "
                 "protecting anything.",
    "tool:Glob": "Locate the artifact when its path is not known. Read-only, returns paths.",
    "tool:Grep": "Locate the offending content inside a large artifact. Read-only.",
}

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

# A published PASS is not indefinitely valid. Session equality alone does not
# survive a host restart or a mid-session dispatch-behaviour change (codex #10),
# so a PASS also expires on wall-clock age and must be re-earned.
PASS_MAX_AGE_SEC = 3600

# `blocked_confirmed` = a denied probe's sentinel was confirmed ABSENT while the
# paired allow-control's sentinel was confirmed PRESENT. `not_applicable` = the
# event was OBSERVED to be non-blocking. Anything else (notably the initial
# `not_established`) is non-passing.
BLOCKING_OUTCOMES_OK = ("blocked_confirmed", "not_applicable")

# Security-critical artefacts whose content is bound alongside the settings
# layers. Hashing settings + VERSION alone would let an edit to the manifest or
# to any enforcement/verification file preserve an existing PASS (codex #6) --
# e.g. moving a protected route outside every surface prefix so it silently
# reports not_protected while the stored PASS stays valid.
BOUND_ARTIFACTS = (
    MANIFEST_RELPATH,
    "hooks/lib/capability_state.py",
    "hooks/pretool-capability-gate.py",
    "hooks/capability-canary.py",
    "scripts/capability-handshake.py",
    "scripts/capability-doctor-strict.py",
    "scripts/capability-status-line.sh",
)


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


def artifact_records(home: Path) -> list[dict]:
    """Content digests of the manifest and every enforcement/verification file."""
    out = []
    for rel in BOUND_ARTIFACTS:
        p = home / rel
        rec = {"path": rel, "present": False, "sha256": None}
        if p.is_file():
            rec["present"] = True
            try:
                rec["sha256"] = sha256_bytes(p.read_bytes())
            except OSError:
                rec["sha256"] = None
        out.append(rec)
    return out


def canonical_binding(home: Path | None = None) -> dict:
    h = harness_home(home)
    return {
        "settings_records": settings_records(h),
        "harness_version": read_harness_version(h),
        "host_build": read_host_build(),
        "artifact_records": artifact_records(h),
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
    arts = binding.get("artifact_records")
    if not isinstance(arts, list) or len(arts) != len(BOUND_ARTIFACTS):
        return "binding_artifacts_malformed"
    for rec, rel in zip(arts, BOUND_ARTIFACTS):
        if not isinstance(rec, dict) or rec.get("path") != rel:
            return "binding_artifacts_malformed"
        if not rec.get("present") or not rec.get("sha256"):
            # An enforcement artefact that is missing or unreadable cannot be
            # bound, so no PASS may rest on it.
            return "binding_artifact_missing"
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
def aggregate_verdict(state: dict, home: Path | None = None,
                      now: float | None = None) -> tuple[str, str | None]:
    """Return (overall, failure_reason). overall is 'PASS' or 'UNPROTECTED'.

    Every failure class carries a DISTINGUISHABLE reason so a negative test can
    prove which mechanism fired (AC-CAPGATE-01 requires this explicitly).
    """
    if state.get("status") == "PENDING":
        return "UNPROTECTED", "state_pending"
    if state.get("status") != "PASS":
        return "UNPROTECTED", f"state_status_{str(state.get('status')).lower()}"

    # A PASS expires on wall-clock age as well as on binding change: same-session
    # equality alone does not survive a host restart or a mid-session change in
    # dispatch behaviour (codex #10). Freshness is re-earned, never assumed.
    completed = _epoch(state.get("completion_time"))
    ref = time.time() if now is None else now
    if completed is None or (ref - completed) > PASS_MAX_AGE_SEC:
        return "UNPROTECTED", "pass_expired"

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
        # The per-event reason is propagated verbatim so failure CLASSES stay
        # distinguishable (a placeholder record for an event that never fired
        # must report missing_event_record, not the identity-check reason that
        # is merely a consequence of having no receipt to identify).
        if ev.get("outcome") != "PASS":
            return "UNPROTECTED", ev.get("failure_reason") or "event_probe_failed"
        if ev.get("event_discriminator") == "unsupported_self_check":
            return "UNPROTECTED", "event_identity_unsupported"
        receipt = ev.get("host_receipt") or {}
        for f in RECEIPT_CORE_FIELDS:
            if not receipt.get(f):
                return "UNPROTECTED", "host_receipt_core_field_missing"
        for f in RECEIPT_TIER3_FIELDS:
            if f not in receipt:
                return "UNPROTECTED", "host_receipt_tier3_field_omitted"
        # CANARY LIVENESS IS NOT ENFORCEMENT (codex finding #3). Every canary
        # exits 0 by design, so a host that dispatches all seven canaries while
        # silently skipping the blocking gate would otherwise reach PASS -- the
        # exact selective-dispatch threat this lane exists to close. A blocking
        # classification that was never established is therefore non-passing.
        if ev.get("blocking_action") not in BLOCKING_OUTCOMES_OK:
            return "UNPROTECTED", "blocking_capability_not_established"

    if not any(e.get("blocking_action") == "blocked_confirmed" for e in by_label.values()):
        # At least one event must have PROVEN a block by sentinel absence.
        return "UNPROTECTED", "no_blocking_capability_proven"

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
        raw = str(ti.get("command") or "").strip()
        # An EMBEDDED control character can hide a second command behind the
        # first (`/do\n/dev`), and .split() would then classify the whole payload
        # on its leading token alone -- which matters most for the exempt hatch
        # routes. Such a payload is not canonicalisable, so it is mapped to a
        # route that sits inside the protected surface and matches nothing,
        # i.e. fail-closed. Surrounding whitespace is stripped first, so an
        # ordinary trailing newline stays benign.
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
            return "slashcommand:<uncanonicalisable>"
        cmd = raw.split()[0:1]
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
        "enforcement_mode": None,
        "exemption": None,
        "timestamp": now_iso(),
    }

    manifest, merr = load_manifest(home, manifest_path)
    if merr:
        # A broken manifest must not strand a human. The escape hatches fall back
        # to the module constant so the recovery path does not depend on the file
        # that just failed to load; every other route still refuses.
        if route in HUMAN_CONSENT_ESCAPE_HATCH_ROUTES:
            record["decision"] = "PERMIT"
            record["exemption"] = "human_consent_escape_hatch_manifest_unavailable"
            return record
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
    # `independent_enforcement` is a COVERAGE annotation -- "does a non-hook
    # callsite exist for this route?" -- and is RECORDED, never used as a verdict
    # input. Refusing on it produced a refusal that NO state could ever satisfy:
    # zero protection on the threat host (where the gate is never dispatched at
    # all) and a permanent, unrepairable block on a healthy one. A route this
    # design cannot independently enforce belongs outside the protected surface,
    # or is enforced by something that can actually be satisfied -- never refused
    # on unsatisfiable grounds. Fail-closed must not mean fail-sealed.
    record["enforcement_mode"] = (
        "independent" if entry.get("independent_enforcement", False) else "gate_only"
    )

    # HUMAN CONSENT ESCAPE HATCH (see the manifest's _escape_hatch_note). These
    # routes are permitted even when state is absent, because blocking them
    # removes the only in-harness path by which a human could authorise a repair
    # -- turning a fail-closed host into a self-sealed one. The exemption is
    # recorded on the decision record so a doctor run can always show which
    # routes were let through and why; it is never silent.
    if entry.get("human_consent_escape_hatch", False):
        record["decision"] = "PERMIT"
        record["exemption"] = "human_consent_escape_hatch"
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
