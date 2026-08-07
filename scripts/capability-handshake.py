#!/usr/bin/env python3
"""Host-capability handshake — nonce-bound, live-host lifecycle probe.

Proves (or refuses to claim) that this harness's hook-based security boundary is
actually live on THIS host, then binds the result to the Claude Code build, the
rendered settings layers and the harness version, and publishes it as an atomic
0600 state file that the in-process consumer and the PreToolUse gate both read.

Design rule inherited from the ticket and enforced throughout: an unverifiable
sub-check reports `unsupported_self_check` WITH A RECORDED REASON. It never
silently passes, and it never authorises activation — per the aggregate formula an
unsupported result blocks exactly as a failure does. The report tells the truth
about WHY; it never softens WHETHER.

Usage:
  capability-handshake.py [--session-id <id>] [--home <dir>] [--state <path>]
                          [--timeout <seconds>] [--json]
  capability-handshake.py --fixture-diagnostic   # supplementary diagnostic ONLY;
                                                 # provably cannot reach PASS
  capability-handshake.py --aggregate-only <state.json>   # unit path, no I/O on
                                                 # any settings layer

Exit codes: 0 = handshake PASS; 1 = UNPROTECTED (any fail/missing/unsupported);
            2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
import capability_state as cs  # noqa: E402

STATUS_MARKER = "UNPROTECTED HOST"
DEFAULT_TIMEOUT = 25


# --------------------------------------------------------------------------- #
# probe fixtures — created under the owner-controlled runtime dir, removed on
# success, failure, timeout AND interrupt.
# --------------------------------------------------------------------------- #
class ProbeFixtures:
    def __init__(self, session_id: str, run_id: str):
        self.dir = cs.state_dir()
        self.probe_file = self.dir / f"probe-{cs.state_path(session_id).stem}.json"
        self.receipts = self.dir / f"receipts-{run_id}.jsonl"
        self.sentinel_dir = self.dir / f"sentinels-{run_id}"

    def create(self, probe: dict) -> None:
        self.sentinel_dir.mkdir(mode=0o700, exist_ok=True)
        cs.write_state_atomic(self.probe_file, probe)

    def cleanup(self) -> None:
        for p in (self.probe_file, self.receipts):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            for child in self.sentinel_dir.iterdir():
                child.unlink()
            self.sentinel_dir.rmdir()
        except OSError:
            pass

    def empty(self) -> bool:
        return not self.probe_file.exists() and not self.receipts.exists() and not self.sentinel_dir.exists()


# --------------------------------------------------------------------------- #
# cross-checks 1-5 (AC-CAPGATE-01)
# --------------------------------------------------------------------------- #
def _ambient_session_id(explicit: str | None) -> str:
    return explicit or os.environ.get("CLAUDE_SESSION_ID") or ""


def transcript_offsets() -> dict[str, int]:
    """Byte sizes of every host transcript at probe-open time.

    Cross-check 4 searches only PAST these offsets, so a nonce that was already
    in the file cannot satisfy it. Without this, "the transcript contains the
    nonce" would be satisfiable by history rather than by this probe window.
    """
    out: dict[str, int] = {}
    root = Path.home() / ".claude" / "projects"
    try:
        for p in root.rglob("*.jsonl"):
            try:
                out[str(p)] = p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return out


def cross_check_event(receipt_rec: dict, label: str, probe: dict, window_start: float,
                      ambient_sid: str) -> tuple[str, str | None, str]:
    """Return (outcome, failure_reason, event_discriminator)."""
    receipt = receipt_rec.get("host_receipt") or {}
    event_nonces = probe.get("event_nonces") or {}

    # (1) EVENT IDENTITY — two named discriminators, unsupported only if NEITHER works.
    discriminator = "unsupported_self_check"
    hen = receipt.get("hook_event_name")
    if hen and hen != cs.ABSENT and hen == label:
        discriminator = "host_field"
    else:
        mine = event_nonces.get(label)
        others = {n for lbl, n in event_nonces.items() if lbl != label}
        blob = json.dumps(receipt_rec, sort_keys=True)
        if mine and receipt_rec.get("nonce") == mine and not any(o in blob for o in others):
            discriminator = "event_key_nonce"
    if discriminator == "unsupported_self_check":
        return "UNSUPPORTED", "event_identity_unsupported", discriminator

    # (2) session_id equals the AMBIENT session's id, not merely self-consistent.
    sid = receipt.get("session_id")
    if not sid:
        return "FAIL", "host_receipt_core_field_missing", discriminator
    if ambient_sid and sid != ambient_sid:
        return "FAIL", "session_id_not_ambient", discriminator

    # (3) transcript exists; internal sessionId == host_receipt.session_id == stem.
    tp = receipt.get("transcript_path")
    if not tp:
        return "FAIL", "host_receipt_core_field_missing", discriminator
    tpath = Path(tp)
    if not tpath.is_file():
        return "FAIL", "transcript_absent", discriminator
    if tpath.stem != sid:
        return "FAIL", "transcript_stem_mismatch", discriminator
    try:
        text = tpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "FAIL", "transcript_unreadable", discriminator
    internal_ok = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("sessionId"):
            internal_ok = rec.get("sessionId") == sid
            break
    if not internal_ok:
        return "FAIL", "transcript_session_mismatch", discriminator

    # (4) the transcript CONTAINS THIS RUN'S NONCE, placed there by the live host
    # AFTER the byte offset recorded when the probe opened. Searching the whole
    # file would accept a nonce that was already present, so the offset is what
    # ties the appearance to this probe window rather than to history. It still
    # does not prove the lifecycle dispatch CAUSED the receipt -- see the
    # honest-limits clause, which names that residual explicitly.
    offset = int((probe.get("transcript_offsets") or {}).get(str(tpath), 0))
    if probe.get("nonce") not in text[offset:]:
        return "FAIL", "transcript_missing_run_nonce", discriminator

    # (5) transcript mtime advanced inside the probe window.
    try:
        if tpath.stat().st_mtime < window_start:
            return "FAIL", "transcript_mtime_stale", discriminator
    except OSError:
        return "FAIL", "transcript_unreadable", discriminator

    return "PASS", None, discriminator


# --------------------------------------------------------------------------- #
# probe phases
# --------------------------------------------------------------------------- #
def collect_receipts(fixtures: ProbeFixtures, timeout: int, expected: int) -> list[dict]:
    deadline = time.time() + timeout
    seen: dict[str, dict] = {}
    while time.time() < deadline:
        try:
            for line in fixtures.receipts.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("event_label"):
                    seen.setdefault(rec["event_label"], rec)
        except OSError:
            pass
        if len(seen) >= expected:
            break
        time.sleep(0.5)
    return list(seen.values())


def build_event_records(receipts: list[dict], probe: dict, window_start: float,
                        ambient_sid: str) -> list[dict]:
    by_label = {r.get("event_label"): r for r in receipts}
    out = []
    for label in cs.RELIED_UPON_EVENTS:
        rec = by_label.get(label)
        if rec is None:
            out.append({
                "event_label": label,
                "nonce": (probe.get("event_nonces") or {}).get(label),
                "run_id": probe.get("run_id"),
                "host_receipt": {},
                "outcome": "FAIL",
                "failure_reason": "missing_event_record",
                "event_discriminator": "unsupported_self_check",
                "blocking_action": "not_established",
                "observation": "no live-host receipt arrived inside the probe window",
            })
            continue
        outcome, reason, disc = cross_check_event(rec, label, probe, window_start, ambient_sid)
        out.append({
            "event_label": label,
            "nonce": rec.get("nonce"),
            "run_id": rec.get("run_id"),
            "host_receipt": rec.get("host_receipt") or {},
            "outcome": outcome,
            "failure_reason": reason,
            "event_discriminator": disc,
            # The nonce discriminator evidences EVENT/REGISTRATION BINDING, not
            # host attestation of the event: the label comes from the argv this
            # repo wrote into the registration, so a host that dispatched every
            # registration under the wrong event would still yield correctly
            # labelled receipts (codex #5). Recording the strength keeps the
            # weaker evidence visible instead of hiding it behind a bare PASS.
            "event_identity_strength": (
                "host_attested" if disc == "host_field"
                else "registration_bound" if disc == "event_key_nonce" else "none"
            ),
            # AC-CAPGATE-02: the blocking classification is UNKNOWN until measured,
            # and is always recorded together with the observation that set it.
            "blocking_action": "not_established",
            "observation": (
                "live receipt observed; blocking capability not yet measured — the "
                "denied/allow-control sentinel pair requires the canary to be "
                "registered in the effective settings (see dev report: registration "
                "deferred on a file-ownership boundary conflict)"
            ),
        })
    return out


def deep_checks_unsupported(reason: str) -> dict:
    """All four deep sub-checks, each individually statused with a recorded reason.

    `unsupported_self_check` is an observable DIAGNOSTIC outcome, never PASS
    evidence: the aggregate formula blocks activation on it exactly as on a fail.
    Reporting a `fail` here instead would misreport an epistemic gap as a measured
    host defect, which the ticket names as itself an AC failure.
    """
    def rec(extra: str) -> dict:
        return {"status": "unsupported_self_check", "reason": f"{reason} {extra}".strip(),
                "evidence": "live-host probe did not run"}

    ordering_reasons = {
        "cross_event_ordering": "relative receipt order needs live receipts for two distinct events; property 1 presupposes property 2 (startup barrier), so a property-2 gap propagates here as one root defect with a dependent consequence, not two independent defects",
        "startup_barrier": "requires observing SessionStart completion against the first tool boundary on a live host",
        "sibling_completion_barrier": "requires observing sibling completion against the host proceeding past the boundary",
        "blocking_precedence": "requires a deny/allow sibling pair with sentinel-absence proof on a live host",
        "declared_order_and_exit2_short_circuit": "relative intra-event order is unobservable without live dispatch; this is the measurement that would empirically settle the declared-order claim for the first time in this tree",
    }
    return {
        "identity_propagation": rec("(needs a real subagent's host-issued identity across live callbacks)"),
        "permission_deny": rec("(needs an actually-denied operation plus an allowed control, both live)"),
        "model_invocation_restriction": rec("(needs real model-originated Skill and SlashCommand paths against a human-only command)"),
        "hook_ordering": {
            "status": "unsupported_self_check",
            "reason": reason,
            "properties": {
                p: {"status": "unsupported_self_check", "reason": f"{reason} {ordering_reasons[p]}"}
                for p in cs.ORDERING_PROPERTIES
            },
        },
    }


def observe_status_surface() -> dict:
    """AC-CAPGATE-05: assert on the RENDERED pane buffer, never on the command's stdout.

    A failure to observe may NEVER be resolved by falling back to stdout
    inspection: an unobservable surface classifies the host unsupported.
    """
    try:
        panes = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_id}"],
                               capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unsupported", "channel": "tmux capture-pane",
                "reason": f"tmux unavailable ({exc})"}
    if panes.returncode != 0 or not panes.stdout.strip():
        return {"status": "unsupported", "channel": "tmux capture-pane",
                "reason": "no attached tmux pane to capture; the rendered marker is unobservable "
                          "in this non-interactive environment"}
    for pane in panes.stdout.split():
        try:
            cap = subprocess.run(["tmux", "capture-pane", "-p", "-e", "-t", pane],
                                 capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if STATUS_MARKER in (cap.stdout or ""):
            red = any(seq in cap.stdout for seq in ("\x1b[31m", "\x1b[91m", "\x1b[41m", "\x1b[101m"))
            return {"status": "observed", "channel": "tmux capture-pane", "pane": pane,
                    "marker": STATUS_MARKER, "ansi_red": red}
    return {"status": "unsupported", "channel": "tmux capture-pane",
            "reason": f"{STATUS_MARKER!r} not present in any captured pane buffer"}


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def run_handshake(session_id: str, home: Path, state_file: Path, timeout: int) -> dict:
    run_id = cs.new_nonce()[:16]
    nonce = cs.new_nonce()
    event_nonces = {label: cs.new_nonce() for label in cs.RELIED_UPON_EVENTS}
    window_start = time.time()
    offsets = transcript_offsets()

    state = {
        "schema_version": cs.SCHEMA_VERSION,
        "status": "PENDING",
        "session_id": session_id,
        "run_id": run_id,
        "nonce": nonce,
        "start_time": cs.now_iso(),
        "completion_time": None,
        "binding": cs.canonical_binding(home),
        "events": [],
        "deep_checks": {},
        "status_surface": {"status": "pending"},
        "overall": "UNPROTECTED",
        "failure_reason": "state_pending",
        "activation_eligible": False,
    }
    # Any prior PASS is atomically replaced with PENDING BEFORE any probe runs.
    cs.write_state_atomic(state_file, state)

    fixtures = ProbeFixtures(session_id, run_id)
    interrupted = {"flag": False}

    def _on_signal(signum, _frame):
        interrupted["flag"] = True
        fixtures.cleanup()
        raise KeyboardInterrupt(f"signal {signum}")

    prev = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    for s in prev:
        try:
            signal.signal(s, _on_signal)
        except (ValueError, OSError):
            pass

    try:
        fixtures.create({"run_id": run_id, "nonce": nonce, "session_id": session_id,
                         "event_nonces": event_nonces, "window_start": window_start,
                         "transcript_offsets": offsets})
        receipts = collect_receipts(fixtures, timeout, len(cs.RELIED_UPON_EVENTS))
        probe = {"run_id": run_id, "nonce": nonce, "event_nonces": event_nonces,
                 "transcript_offsets": offsets}
        state["events"] = build_event_records(receipts, probe, window_start,
                                              _ambient_session_id(session_id))
        got = sum(1 for e in state["events"] if e["outcome"] == "PASS")
        state["deep_checks"] = deep_checks_unsupported(
            "no live-host lifecycle dispatch was observed in this run"
            if got == 0 else "live dispatch partially observed; deep probes not run"
        )
        state["status_surface"] = observe_status_surface()
        state["completion_time"] = cs.now_iso()

        # Evaluate the aggregate over the COMPLETED evidence. The on-disk status is
        # still PENDING at this point (that is the fail-closed guarantee while the
        # run is in flight); judging the in-flight status here would short-circuit
        # on `state_pending` and mask the real failure class.
        overall, reason = cs.aggregate_verdict(dict(state, status="PASS"), home)
        state["overall"] = overall
        state["failure_reason"] = reason
        state["status"] = "PASS" if overall == "PASS" else "FAIL"
        state["activation_eligible"] = overall == "PASS"
        # PASS is published atomically only after full validation completes.
        cs.write_state_atomic(state_file, state)
        return state
    finally:
        fixtures.cleanup()
        for s, h in prev.items():
            try:
                signal.signal(s, h)
            except (ValueError, OSError):
                pass


def fixture_diagnostic(session_id: str, home: Path) -> dict:
    """Supplementary diagnostic ONLY — the falsifiability proof for AC-CAPGATE-01.

    Pipes a synthetic envelope straight into the canary (today's canary-verify.sh
    technique). It produces a receipt, yet provably cannot satisfy cross-checks
    3-5 without fabricating a transcript file, so it is recorded diagnostic_only
    and can never set overall=PASS.
    """
    run_id = cs.new_nonce()[:16]
    nonce = cs.new_nonce()
    event_nonces = {label: cs.new_nonce() for label in cs.RELIED_UPON_EVENTS}
    fixtures = ProbeFixtures(session_id, run_id)
    window_start = time.time()
    try:
        offsets = transcript_offsets()
        fixtures.create({"run_id": run_id, "nonce": nonce, "session_id": session_id,
                         "event_nonces": event_nonces, "window_start": window_start,
                         "transcript_offsets": offsets})
        canary = Path(__file__).resolve().parent.parent / "hooks" / "capability-canary.py"
        for label in cs.RELIED_UPON_EVENTS:
            envelope = json.dumps({
                "session_id": session_id,
                "transcript_path": f"/nonexistent/{session_id}.jsonl",
                "cwd": os.getcwd(),
                "hook_event_name": label,
            })
            subprocess.run([sys.executable, str(canary), label], input=envelope,
                           capture_output=True, text=True, timeout=30, check=False)
        receipts = collect_receipts(fixtures, 2, len(cs.RELIED_UPON_EVENTS))
        probe = {"run_id": run_id, "nonce": nonce, "event_nonces": event_nonces,
                 "transcript_offsets": offsets}
        events = build_event_records(receipts, probe, window_start, session_id)
        return {
            "mode": "diagnostic_only",
            "receipts_produced": len(receipts),
            "events": events,
            "overall": "UNPROTECTED",
            "failure_reason": next((e["failure_reason"] for e in events if e["failure_reason"]), None),
            "note": "fixture path cannot satisfy cross-checks 3-5 without fabricating a transcript",
        }
    finally:
        fixtures.cleanup()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--home", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--fixture-diagnostic", action="store_true")
    ap.add_argument("--aggregate-only", default=None,
                    help="evaluate the aggregate formula against an existing state file; "
                         "touches no settings layer")
    args = ap.parse_args(argv)

    home = cs.harness_home(args.home)
    session_id = _ambient_session_id(args.session_id) or f"noninteractive-{os.getpid()}"

    if args.aggregate_only:
        try:
            state = json.loads(Path(args.aggregate_only).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"capability-handshake: cannot read state ({exc})\n")
            return 2
        overall, reason = cs.aggregate_verdict(state, home)
        print(json.dumps({"overall": overall, "failure_reason": reason}, indent=1))
        return 0 if overall == "PASS" else 1

    if args.fixture_diagnostic:
        print(json.dumps(fixture_diagnostic(session_id, home), indent=1))
        return 1  # a diagnostic run is never a PASS

    state_file = Path(args.state) if args.state else cs.state_path(session_id)
    state = run_handshake(session_id, home, state_file, args.timeout)
    if args.as_json:
        print(json.dumps(state, indent=1, sort_keys=True))
    else:
        print(f"capability-handshake: {state['overall']}"
              + (f" ({state['failure_reason']})" if state["failure_reason"] else ""))
    return 0 if state["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
