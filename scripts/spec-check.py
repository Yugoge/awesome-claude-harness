#!/usr/bin/env python3
"""spec-check.py -- THE ONLY legal writer for cp-state files.

Subcommands: check-in, mark, waive, status, check-out, unlock.

cp-state path: $CLAUDE_PROJECT_DIR/.claude/specs/<spec-id>/cp-state-<agent-type>[-<instance-id>].json
Schema: matches cp_state_schema_v1 in context-20260421-060000.json.

Instance slots
--------------
Primary slot is cp-state-<agent>.json. When a second concurrent instance of the
same agent type checks in, check-in auto-allocates the next available integer
suffix (cp-state-<agent>-2.json, -3.json, ...). Caller sees the actual file
path via the check-in output line.

All follow-up operations (mark, waive, status, check-out) accept an optional
--instance-id to target a specific numbered slot. Without it they target the
primary slot. `unlock` clears every slot (primary + numbered) for the spec.

BOTH check-in branches -- slot allocation and ``--bump-generation`` -- run
inside the shared checkpoint directory transaction from
``hooks/lib/checkpoint_resources.py``, because both write the PRIMARY file and
two writers of one file serialising on two different lock files do not exclude
each other.  A missing, corrupt, or empty primary template fails closed rather
than creating an unusable numbered slot.  mark/waive/check-out/unlock retain
their existing per-file locks. All timestamps are ISO-8601 UTC.

Usage:
  spec-check.py check-in   --spec-id SID --agent AGENT --agent-id AID [--artifact PATH]
  spec-check.py mark       --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID] --cp-id CP_ID
  spec-check.py waive      --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID] --cp-id CP_ID
  spec-check.py status     --spec-id SID [--agent AGENT] [--instance-id N]
  spec-check.py check-out  --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID]
  spec-check.py unlock     --spec-id SID

Exit codes: 0=ok, 1=failure.
"""

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

from lib import checkpoint_resources


ALLOWED_AGENTS = (
    # Core /spec, /dev, and /dev-overnight roles.
    "architect", "ba", "dev", "pm", "product-owner", "qa",
    "ui-specialist", "user",
    # Command/overnight specialist roles.  These must be first-class
    # cp-state actors too; otherwise their checklists cannot be enforced by
    # subagentstop-cp-enforce.py after check-in.
    "cleaner", "cleanliness-inspector", "git-edge-case-analyst",
    "prompt-inspector", "rule-inspector", "spec", "style-inspector",
    "test-executor", "test-validator",
    # Test-writer agent (spec-20260518-225715 §5.2 / Cycle 2 P1.1 codex finding #1):
    # registered here so check-in / mark / waive accept the role symmetrically
    # with hooks/pretool-cp-checkin.py CP_AGENTS + hooks/prompt-workflow.py
    # agent_types. Without this, test-writer's cp-state lifecycle would 404.
    "test-writer",
    # Graphify enrichment subagent (spec-20260527-061433): registered here
    # symmetrically with CP_AGENTS (hooks/pretool-cp-checkin.py) and
    # agent_types (hooks/prompt-workflow.py) per arch-2 precedent.
    "graphify",
)

ALLOWED_STATES = ("pending", "done", "waived-with-reason")


def _now_iso_z():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _project_dir():
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def _cp_dir(spec_id):
    return _project_dir() / ".claude" / "specs" / spec_id


def _cp_file(spec_id, agent, instance_id=None):
    """Return the cp-state path for a given (spec, agent, instance-slot).

    instance_id=None  -> primary slot: cp-state-<agent>.json
    instance_id=<int> -> numbered slot: cp-state-<agent>-<N>.json
    """
    suffix = f"-{instance_id}" if instance_id else ""
    return _cp_dir(spec_id) / f"cp-state-{agent}{suffix}.json"


def _all_instance_files(spec_id, agent):
    """Return every cp-state file (primary + numbered) for an agent under a spec.

    Returns a list of (instance_id, path) tuples, primary first (instance_id=None),
    then numbered slots in ascending integer order.
    """
    cp_dir = _cp_dir(spec_id)
    if not cp_dir.exists():
        return []
    primary = _cp_file(spec_id, agent)
    files = []
    if primary.exists():
        files.append((None, primary))
    pattern = re.compile(rf"^cp-state-{re.escape(agent)}-(\d+)\.json$")
    numbered = []
    for child in cp_dir.iterdir():
        m = pattern.match(child.name)
        if m:
            numbered.append((int(m.group(1)), child))
    numbered.sort(key=lambda pair: pair[0])
    files.extend(numbered)
    return files


def _default_payload(spec_id, agent, instance_id=None):
    return {
        "spec_id": spec_id,
        "agent_type": agent,
        "instance_id": instance_id,
        "generation": 1,  # P2 ba-spec-20260427-194324
        "agent_id": None,
        "is_running": False,
        "checked_in_at": None,
        "checked_out_at": None,
        "checkpoints": [],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }


def _read_payload(spec_id, agent, instance_id=None):
    path = _cp_file(spec_id, agent, instance_id)
    if not path.exists():
        return _default_payload(spec_id, agent, instance_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"WARN: corrupt cp-state {path}: {exc}; reinitializing\n")
        return _default_payload(spec_id, agent, instance_id)


def _write_payload(spec_id, agent, payload, instance_id=None):
    path = _cp_file(spec_id, agent, instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _validate_agent(agent):
    if agent not in ALLOWED_AGENTS:
        sys.stderr.write(f"ERROR: unknown agent '{agent}' (allowed: {', '.join(ALLOWED_AGENTS)})\n")
        return False
    return True


def _stamp_runtime(payload, args, instance_id):
    payload["instance_id"] = instance_id
    payload["agent_id"] = args.agent_id or payload.get("agent_id")
    payload["is_running"] = True
    payload["checked_in_at"] = _now_iso_z()
    payload["checked_out_at"] = None
    if args.artifact:
        payload["terminal_artifact"]["path"] = args.artifact


def _bump_and_reset(payload, actor=None):
    """P2 ba-spec-20260427-194324: increment generation, reset all
    checkpoints to pending, clear waived_reason, refresh updated_at on
    every checkpoint AND on the cp-state-level marker.

    AUDIT-PRESERVING (parent RULING_5 outstanding liability): a checkpoint
    that is waived-with-reason carries the ONLY surviving record that its
    holder waived under duress rather than falsely marking it done. Clearing
    waived_reason without an audit row destroys that record, so the prior
    state/reason/updated_at are appended to audit_history first -- the same
    shape mark uses -- with transitioned_to 'pending'.
    """
    now = _now_iso_z()
    payload["generation"] = int(payload.get("generation", 1)) + 1
    payload["updated_at"] = now
    for cp in payload.get("checkpoints", []):
        if cp.get("state") == "waived-with-reason":
            _append_waived_audit(cp, actor, now, transitioned_to="pending")
        cp["state"] = "pending"
        cp["waived_reason"] = None
        cp["updated_at"] = now


def _check_in_rmw(args, instance_id):
    """Read-modify-write the cp-state file under fcntl.LOCK_EX so concurrent
    --bump-generation invocations cannot tear (AC10d).

    The per-file lock is nested INSIDE the shared checkpoint directory
    transaction so a concurrent --bump-generation and a concurrent plain
    check-in -- which both write the PRIMARY file -- cannot run at the same
    time. Serialising two writers of one file on two different lock files
    does not exclude them, which is the defect this nesting closes.
    """
    path = _cp_file(args.spec_id, args.agent, instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    primary_path = _cp_file(args.spec_id, args.agent, None)
    with checkpoint_resources.directory_transaction(primary_path):
        lock_path = path.with_suffix(path.suffix + ".lock")
        with open(lock_path, "w") as lh:
            fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
            try:
                payload = _read_payload(args.spec_id, args.agent, instance_id)
                _stamp_runtime(payload, args, instance_id)
                if getattr(args, "bump_generation", False):
                    _bump_and_reset(payload, getattr(args, "agent_id", None))
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            finally:
                fcntl.flock(lh.fileno(), fcntl.LOCK_UN)


def _enforce_reset_scope(args):
    """Apply the cross-role ownership refusal to the audit-preserving reset.

    mark and waive already refuse cross-role mutation unconditionally. A reset
    path that skipped the same check would open a hole in an existing contract,
    so --bump-generation runs it over every checkpoint id it is about to
    re-open. Returns 0 to proceed, 1 to refuse.
    """
    payload = _read_payload(args.spec_id, args.agent, None)
    for cp in payload.get("checkpoints", []) or []:
        cp_id = cp.get("id")
        if not cp_id:
            continue
        if _enforce_cross_role_scope(args.spec_id, args.agent, cp_id,
                                     "bump-generation reset") != 0:
            return 1
    return 0


def _cmd_check_in(args):
    if not _validate_agent(args.agent):
        return 1
    if getattr(args, "bump_generation", False):
        # Explicit generation bumps intentionally compose on the primary file.
        if _enforce_reset_scope(args) != 0:
            return 1
        _check_in_rmw(args, None)
        instance_id = None
        path = _cp_file(args.spec_id, args.agent, None)
    else:
        primary_path = _cp_file(args.spec_id, args.agent, None)

        def _claim_primary(payload):
            _stamp_runtime(payload, args, None)
            return payload

        result = checkpoint_resources.claim_slot(
            primary_path,
            agent_id=args.agent_id,
            artifact=args.artifact,
            primary_updater=_claim_primary,
        )
        if result.get("status") != "pass":
            # AC-LB-06 is a machine contract: do not decorate this object.
            print(json.dumps({
                "status": "fail",
                "numbered_path": None,
                "error_code": result.get("error_code"),
            }, sort_keys=True))
            return 1
        instance_id = result.get("instance_id")
        path = Path(result["path"])
    slot_label = "primary" if instance_id is None else f"instance-id={instance_id}"
    agent_id_label = f" agent-id={args.agent_id}" if args.agent_id else ""
    print(f"checked in: spec={args.spec_id} agent={args.agent} slot={slot_label}{agent_id_label}")
    print(f"cp-state-path: {path}")
    return 0


def _find_cp(payload, cp_id):
    for cp in payload.get("checkpoints", []):
        if cp.get("id") == cp_id:
            return cp
    return None


# Filename pattern: cp-state-<role>.json or cp-state-<role>-<instance>.json.
# Owner role for any cp-id is the <role> embedded in the filename of the
# cp-state file that contains it. Used by mark/waive to refuse cross-role
# operations unconditionally (no env, no override, no sentinel bypass).
_CP_STATE_FILENAME_RE = re.compile(r"^cp-state-([A-Za-z0-9_-]+?)(?:-(\d+))?\.json$")


def _file_contains_cp_id(path, cp_id):
    """Return True iff path is a parseable cp-state file containing cp-id."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return any(cp.get("id") == cp_id for cp in data.get("checkpoints", []) or [])


def _agent_owns_cp_id(spec_id, agent, cp_id):
    """True iff cp-id is in any of --agent's own slot files (primary +
    numbered). Agent-first ownership: caller's own file wins regardless of
    same-id collisions in other roles' cp-state files (collisions are the
    norm -- e.g. cp-01 reused across all 8 roles)."""
    for _iid, path in _all_instance_files(spec_id, agent):
        if _file_contains_cp_id(path, cp_id):
            return True
    return False


def _find_other_role_owner(spec_id, agent, cp_id):
    """Return (other_role, path) for the first cp-state file NOT owned by
    --agent that contains cp-id, else (None, None)."""
    cp_dir = _cp_dir(spec_id)
    if not cp_dir.exists():
        return (None, None)
    for child in sorted(cp_dir.iterdir()):
        m = _CP_STATE_FILENAME_RE.match(child.name)
        if not m or m.group(1) == agent:
            continue
        if _file_contains_cp_id(child, cp_id):
            return (m.group(1), child)
    return (None, None)


def _enforce_cross_role_scope(spec_id, agent, cp_id, op_label):
    """Agent-first cross-role refusal. Allow if caller's own file owns cp-id;
    refuse if another role owns it; pass-through if nobody owns it (so the
    caller's downstream not-found error surfaces). UNCONDITIONAL refusal:
    no env override, no sentinel, no orchestrator bypass."""
    if _agent_owns_cp_id(spec_id, agent, cp_id):
        return 0
    other_role, other_path = _find_other_role_owner(spec_id, agent, cp_id)
    if other_role is None:
        return 0
    sys.stderr.write(
        f"ERROR: cross-role {op_label} forbidden: cp-id '{cp_id}' is "
        f"owned by role '{other_role}' (file: {other_path.name}); "
        f"--agent '{agent}' may only {op_label} checkpoints owned by "
        f"role '{agent}'. There is no override flag, no sentinel bypass, "
        f"and no orchestrator escape. If a cross-role state genuinely "
        f"needs reconciliation, escalate to the user for a manual "
        f"cp-state JSON edit.\n"
    )
    return 1


def _resolve_payload_for_actor(spec_id, agent, instance_id, agent_id, op_label):
    """Return (instance_id, payload) for an operation performed by agent_id.

    If --agent-id is supplied, it is authoritative: locate the cp-state slot
    whose stored agent_id matches it. This makes parallel same-role slots safe
    even when the subagent only knows the primary cp-state filename from the
    prompt. If --instance-id is also supplied, validate that the addressed slot
    belongs to the supplied agent_id.

    If --agent-id is omitted, preserve legacy primary-slot behavior for
    read-only/manual workflows, except check-out uses a stricter wrapper below.
    """
    if instance_id is not None:
        payload = _read_payload(spec_id, agent, instance_id)
        current = payload.get("agent_id")
        if agent_id and current and current != agent_id:
            sys.stderr.write(
                f"ERROR: {op_label} ownership mismatch: slot instance-id="
                f"{instance_id} belongs to agent_id '{current}', not "
                f"'{agent_id}'\n"
            )
            return None, None
        return instance_id, payload

    if agent_id:
        matches = []
        for iid, _path in _all_instance_files(spec_id, agent):
            payload = _read_payload(spec_id, agent, iid)
            if payload.get("agent_id") == agent_id:
                matches.append((iid, payload))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            sys.stderr.write(
                f"ERROR: {op_label} ambiguous: agent_id '{agent_id}' "
                f"matches {len(matches)} cp-state slots for role '{agent}'\n"
            )
            return None, None
        sys.stderr.write(
            f"ERROR: {op_label} forbidden: no cp-state slot for role "
            f"'{agent}' is owned by agent_id '{agent_id}'\n"
        )
        return None, None

    return None, _read_payload(spec_id, agent, None)


def _all_cps_terminal(payload):
    """C7: True iff every cp is in a terminal state (done/waived-with-reason)."""
    cps = payload.get("checkpoints") or []
    return bool(cps) and all(cp.get("state") in ("done", "waived-with-reason") for cp in cps)


def _refresh_terminal_artifact(payload):
    """F7: refresh terminal_artifact.exists by os.path.exists; stamp validated_at."""
    ta = payload.get("terminal_artifact")
    if isinstance(ta, dict) and ta.get("path"):
        ta["exists"] = os.path.exists(ta["path"])
        ta["validated_at"] = _now_iso_z()


def _write_payload_with_auto_checkout(spec_id, agent, payload, iid):
    """C7: write payload, auto-flipping is_running to False if all cps terminal. F7: refresh terminal_artifact."""
    if payload.get("is_running") and _all_cps_terminal(payload):
        payload["is_running"], payload["checked_out_at"] = False, _now_iso_z()
    _refresh_terminal_artifact(payload)
    _write_payload(spec_id, agent, payload, iid)


def _check_lifecycle_open(payload):
    """F8: refuse mutations on closed cp-state. AC2: lifecycle closed + Re-check-in required."""
    if not payload.get("is_running") and payload.get("checked_out_at"):
        sys.stderr.write(
            f"ERROR: cp-state lifecycle closed at {payload['checked_out_at']}; "
            f"refusing mutation. Re-check-in required to mutate.\n"
        )
        return False
    return True


def _append_waived_audit(cp, actor, now_iso, transitioned_to="done"):
    """F6: preserve waiver context per AC4 minimum-keys schema.

    transitioned_to is a PARAMETER, not the literal 'done': the reset path
    re-opens a waived checkpoint to 'pending', and recording 'done' there
    would write a false transition into the audit trail.
    """
    cp.setdefault("audit_history", []).append({
        "prior_state": "waived-with-reason", "prior_waived_reason": cp.get("waived_reason"),
        "prior_updated_at": cp.get("updated_at"), "transitioned_to": transitioned_to,
        "transitioned_at": now_iso, "actor": actor,
    })


def _apply_mark_transition(cp, cp_id, actor):
    """F5/F6: idempotent re-mark + waiver-audit preservation. Returns: 0=already-done, 1=transition."""
    if cp.get("state") == "done":  # F5/AC3: idempotent re-mark, exact wording
        sys.stderr.write(f"{cp_id} already done at {cp.get('updated_at')}\n")
        return 0
    now = _now_iso_z()
    if cp.get("state") == "waived-with-reason":  # F6: audit before clearing (uses prior updated_at)
        _append_waived_audit(cp, actor, now)
    cp["state"] = "done"
    cp["waived_reason"] = None
    cp["updated_at"] = now
    return 1


def _cmd_mark(args):
    if not _validate_agent(args.agent):
        return 1
    if _enforce_cross_role_scope(args.spec_id, args.agent, args.cp_id, "mark") != 0:
        return 1
    iid, payload = _resolve_payload_for_actor(
        args.spec_id,
        args.agent,
        getattr(args, "instance_id", None),
        getattr(args, "agent_id", None),
        "mark",
    )
    if payload is None or not _check_lifecycle_open(payload):
        return 1
    cp = _find_cp(payload, args.cp_id)
    if cp is None:
        sys.stderr.write(f"ERROR: cp-id '{args.cp_id}' not found\n")
        return 1
    rc_t = _apply_mark_transition(cp, args.cp_id, getattr(args, "agent_id", None))
    _write_payload_with_auto_checkout(args.spec_id, args.agent, payload, iid)
    if rc_t == 0:
        return 0
    print(f"marked done: {args.cp_id}")
    return 0


def _cmd_waive(args):
    if not _validate_agent(args.agent):
        return 1
    if _enforce_cross_role_scope(args.spec_id, args.agent, args.cp_id, "waive") != 0:
        return 1
    iid, payload = _resolve_payload_for_actor(
        args.spec_id,
        args.agent,
        getattr(args, "instance_id", None),
        getattr(args, "agent_id", None),
        "waive",
    )
    if payload is None or not _check_lifecycle_open(payload):  # F8
        return 1
    cp = _find_cp(payload, args.cp_id)
    if cp is None:
        sys.stderr.write(f"ERROR: cp-id '{args.cp_id}' not found\n")
        return 1
    actor = getattr(args, "agent_id", None) or "unknown"
    auto_reason = f"waived by {actor} at {_now_iso_z()}"
    cp["state"] = "waived-with-reason"
    cp["waived_reason"] = auto_reason
    cp["updated_at"] = _now_iso_z()
    _write_payload_with_auto_checkout(args.spec_id, args.agent, payload, iid)
    print(f"waived: {args.cp_id} ({auto_reason})")
    return 0


def _cmd_status(args):
    cp_dir = _cp_dir(args.spec_id)
    if not cp_dir.exists():
        print(f"no cp-state directory for spec: {args.spec_id}")
        return 0
    agents = [args.agent] if args.agent else ALLOWED_AGENTS
    iid_filter = getattr(args, "instance_id", None)
    found_any = False
    for agent in agents:
        slots = _all_instance_files(args.spec_id, agent)
        if iid_filter is not None:
            slots = [(iid, p) for (iid, p) in slots if iid == iid_filter]
        for iid, _path in slots:
            found_any = True
            payload = _read_payload(args.spec_id, agent, iid)
            _print_agent_status(agent, iid, payload)
    if not found_any:
        if iid_filter is not None:
            print(f"no cp-state files for instance-id={iid_filter} under {cp_dir}")
        else:
            print(f"no cp-state files under {cp_dir}")
    return 0


def _print_agent_status(agent, instance_id, payload):
    label = agent if instance_id is None else f"{agent}#{instance_id}"
    print(f"[{label}]")
    print(f"  running:      {payload.get('is_running')}")
    print(f"  checked_in:   {payload.get('checked_in_at')}")
    print(f"  checked_out:  {payload.get('checked_out_at')}")
    cps = payload.get("checkpoints", [])
    print(f"  checkpoints:  {len(cps)} total")
    for cp in cps:
        state = cp.get("state", "?")
        suffix = ""
        if state == "waived-with-reason":
            suffix = f" ({cp.get('waived_reason', '')})"
        print(f"    - {cp.get('id')}: {state}{suffix}")


def _cmd_check_out(args):
    if not _validate_agent(args.agent):
        return 1
    agent_id = getattr(args, "agent_id", None)
    iid, payload = _resolve_payload_for_actor(
        args.spec_id,
        args.agent,
        getattr(args, "instance_id", None),
        agent_id,
        "check-out",
    )
    if payload is None:
        return 1
    current_agent_id = payload.get("agent_id")
    if payload.get("is_running") and current_agent_id and not agent_id:
        sys.stderr.write(
            "ERROR: check-out ownership validation requires --agent-id for "
            f"running slot owned by agent_id '{current_agent_id}'\n"
        )
        return 1
    if agent_id and current_agent_id and current_agent_id != agent_id:
        sys.stderr.write(
            f"ERROR: check-out ownership mismatch: slot belongs to "
            f"agent_id '{current_agent_id}', not '{agent_id}'\n"
        )
        return 1
    payload["is_running"] = False
    payload["checked_out_at"] = _now_iso_z()
    payload["agent_id"] = None
    _write_payload(args.spec_id, args.agent, payload, iid)
    slot_label = "primary" if iid is None else f"instance-id={iid}"
    print(f"checked out: spec={args.spec_id} agent={args.agent} slot={slot_label}")
    return 0


def _cmd_unlock(args):
    cp_dir = _cp_dir(args.spec_id)
    if not cp_dir.exists():
        print(f"no cp-state directory for spec: {args.spec_id}")
        return 0
    cleared = 0
    for agent in ALLOWED_AGENTS:
        for iid, _path in _all_instance_files(args.spec_id, agent):
            payload = _read_payload(args.spec_id, agent, iid)
            payload["is_running"] = False
            payload["checked_out_at"] = _now_iso_z()
            payload["agent_id"] = None
            _write_payload(args.spec_id, agent, payload, iid)
            cleared += 1
    print(f"unlocked {cleared} cp-state file(s) for spec: {args.spec_id}")
    return 0


def _parse_args():
    p = argparse.ArgumentParser(description="Write cp-state files (only legal writer).")
    sub = p.add_subparsers(dest="cmd", required=True)

    _add_check_in_cmd(sub)
    _add_mark_cmd(sub)
    _add_waive_cmd(sub)
    _add_status_cmd(sub)
    _add_check_out_cmd(sub)
    _add_unlock_cmd(sub)

    return p.parse_args()


def _add_check_in_cmd(sub):
    sp = sub.add_parser("check-in", help="Register subagent as running against a spec")
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--artifact", default=None)
    sp.add_argument("--bump-generation", dest="bump_generation",
                    action="store_true", default=False)


def _add_mark_cmd(sub):
    sp = sub.add_parser("mark", help="Mark a checkpoint as done")
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--instance-id", type=int, default=None)
    sp.add_argument("--agent-id", default=None)
    sp.add_argument("--cp-id", required=True)


def _add_waive_cmd(sub):
    sp = sub.add_parser("waive", help="Waive a checkpoint (auto-text records actor + ISO timestamp)")
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--instance-id", type=int, default=None)
    sp.add_argument("--agent-id", default=None)
    sp.add_argument("--cp-id", required=True)


def _add_status_cmd(sub):
    sp = sub.add_parser("status", help="Print cp-state for a spec")
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", default=None)
    sp.add_argument("--instance-id", type=int, default=None)


def _add_check_out_cmd(sub):
    sp = sub.add_parser("check-out", help="Mark subagent as exited cleanly")
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--instance-id", type=int, default=None)
    sp.add_argument("--agent-id", default=None)


def _add_unlock_cmd(sub):
    sp = sub.add_parser("unlock", help="Clear all locks for a spec (primary and numbered)")
    sp.add_argument("--spec-id", required=True)


HANDLERS = {
    "check-in": _cmd_check_in,
    "mark": _cmd_mark,
    "waive": _cmd_waive,
    "status": _cmd_status,
    "check-out": _cmd_check_out,
    "unlock": _cmd_unlock,
}


def main():
    args = _parse_args()
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        sys.stderr.write(f"ERROR: unknown command '{args.cmd}'\n")
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
