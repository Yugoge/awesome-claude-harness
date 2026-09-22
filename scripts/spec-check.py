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

Concurrency and atomicity
-------------------------
Every mutating subcommand (check-in, mark, waive, check-out, unlock) is one critical
section per spec. It takes the directory lock, an exclusive flock on
<spec dir>/.cp-checkin.lock (the file the read-trigger hook also uses; never unlinked or
truncated), and holds it across the whole read, resolve, modify and write. Inside it each
slot write takes the slot lock, the sidecar cp-state-<agent>[-N].json.lock. The directory
lock is taken before the slot lock, never the other way round, and no code holds two slot
locks at once. status only reads and takes no lock. Both waits are bounded: the lock is
polled without blocking until SPEC_CHECK_LOCK_TIMEOUT_SECONDS seconds have passed (default
10; 0 tries once; an invalid value means the default), then the command exits 75
(EX_TEMPFAIL), which is retryable: run the same command again. Slot files are replaced
atomically (temporary file in the same directory, flush, fsync, os.replace), so lock-free
readers see the old or the new file and never a fragment; a failed write leaves the
previous file intact, removes the temporary file and exits 1 naming the slot file.

Missing files default-initialize; corrupt files are overwritten (fail-forward) with a
stderr warning. All timestamps are ISO-8601 UTC.

Slot lifecycle
--------------
A slot is open from registration (check-in, or the read-trigger hook taking over
an idle slot) until the first of: the mark or waive write that leaves the last checkpoint
terminal (auto-close: is_running false, checked_out_at set, agent_id KEPT),
check-out (agent_id cleared) or unlock (agent_id cleared). A slot registered while
every checkpoint is already terminal has no such write ahead of it: it closes on
its next mark or waive (a repeat done mark included) or on check-out.

A closed slot accepts exactly two mutations, both only from its recorded owner (the
caller whose non-empty --agent-id equals the slot's agent_id): mark of a done
checkpoint (idempotent, exit 0, nothing written) and mark of a waived-with-reason
checkpoint (upgraded to done, exit 0, recorded in audit_history with after_close
true and slot_closed_at; the slot stays closed). Everything else exits 1, writes
nothing and names the closing time and a remedy: waive (always), mark of a pending
or unknown checkpoint, and any caller who is not the recorded owner (other id, no
id, cleared owner).

To keep marking after a refusal the recorded owner runs check-in with its own
--agent-id: it re-opens the idle slot recorded for that id (else the first idle slot
of the role), keeps every checkpoint state and re-binds ownership.
--bump-generation is not a re-open: it resets every checkpoint to pending. A
check-in by an id that owns no slot takes over the first idle slot of the role and
its previous owner then fails with "no cp-state slot ... is owned by agent_id"; the
read-trigger hook can re-bind a finished slot the same way.

Usage:
  spec-check.py check-in   --spec-id SID --agent AGENT --agent-id AID [--artifact PATH]
  spec-check.py mark       --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID] --cp-id CP_ID
  spec-check.py waive      --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID] --cp-id CP_ID
  spec-check.py status     --spec-id SID [--agent AGENT] [--instance-id N]
  spec-check.py check-out  --spec-id SID --agent AGENT [--instance-id N] [--agent-id AID]
  spec-check.py unlock     --spec-id SID

Exit codes: 0 ok, 1 refused, 2 usage, 75 lock timeout (retryable). 1 covers ownership, lifecycle, cross-role
and ambiguous-slot refusals; 2 covers argument-parsing errors and a blank --agent-id.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


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

# Concurrency model (see the module docstring).
LOCK_FILE_NAME = ".cp-checkin.lock"
LOCK_TIMEOUT_ENV = "SPEC_CHECK_LOCK_TIMEOUT_SECONDS"
LOCK_TIMEOUT_DEFAULT_SECONDS = 10.0
LOCK_POLL_SECONDS = 0.005
EXIT_LOCK_TIMEOUT = 75  # EX_TEMPFAIL: nothing was changed, run the same command again
READ_ONLY_COMMANDS = ("status",)
TEMP_NAME_ATTEMPTS = 8


class LockTimeout(Exception):
    """A bounded lock wait expired; the caller may retry."""

    def __init__(self, label, seconds):
        super().__init__(label)
        self.label = label
        self.seconds = seconds


class SpecCheckIOError(Exception):
    """A lock could not be opened or a slot write failed; str() is the user-facing text."""


def _lock_timeout_seconds():
    """Finite float >= 0 from the environment; anything else (unset, empty, negative,
    nan, inf, not a number) means the default."""
    raw = os.environ.get(LOCK_TIMEOUT_ENV)
    if raw is None:
        return LOCK_TIMEOUT_DEFAULT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return LOCK_TIMEOUT_DEFAULT_SECONDS
    if value != value or value < 0 or value == float("inf"):
        return LOCK_TIMEOUT_DEFAULT_SECONDS
    return value


def _flock_bounded(fd, label):
    """Take LOCK_EX by non-blocking polls; raise LockTimeout at the deadline."""
    timeout = _lock_timeout_seconds()
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LockTimeout(label, timeout)
            time.sleep(LOCK_POLL_SECONDS)


@contextlib.contextmanager
def _locked_file(lock_path, label):
    """Hold an exclusive flock on `lock_path` (created if absent, never truncated, never
    unlinked). Closing the descriptor releases the lock, also on process death."""
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o666)
    except OSError as exc:
        raise SpecCheckIOError(
            f"cannot open {label} {lock_path}: {exc}; nothing was changed; fix the cause and retry"
        ) from exc
    try:
        _flock_bounded(fd, label)
        yield
    finally:
        os.close(fd)


def _slot_lock(path):
    """Per-slot sidecar lock cp-state-<agent>[-N].json.lock; nested inside the directory lock."""
    return _locked_file(path.with_suffix(path.suffix + ".lock"), f"slot lock {path.name}.lock")


@contextlib.contextmanager
def _spec_dir_lock(cp_dir, create):
    """The per-spec directory lock, <spec dir>/.cp-checkin.lock, shared with the read-trigger hook."""
    if create:
        try:
            cp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SpecCheckIOError(f"cannot create {cp_dir}: {exc}; nothing was changed; retry") from exc
    with _locked_file(cp_dir / LOCK_FILE_NAME, f"directory lock {LOCK_FILE_NAME}"):
        yield


def _atomic_write_text(path, text):
    """Replace `path` with `text` atomically: temporary file in the same directory (dot-prefixed
    name, never matching cp-state-*.json), flush, fsync, os.replace. A pre-existing file with a
    colliding temporary name is never overwritten (O_EXCL, new random suffix). On any failure
    the temporary file is removed and the previous file is left untouched."""
    tmp = None
    try:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            mode = None
        fd = None
        for _attempt in range(TEMP_NAME_ATTEMPTS):
            candidate = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o666)
            except FileExistsError:
                continue
            tmp = candidate
            break
        if fd is None:
            raise FileExistsError(f"no free temporary name beside {path.name}")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if mode is not None:
                os.fchmod(fh.fileno(), mode)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException as exc:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if isinstance(exc, OSError):
            raise SpecCheckIOError(
                f"cp-state write failed for {path.name}: {exc}; the previous {path.name} "
                f"is intact and nothing was changed; safe to retry"
            ) from exc
        raise


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


def _is_running(path):
    """Return True if the cp-state file at `path` is flagged is_running."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("is_running"))


def _allocate_instance_id(spec_id, agent):
    """Find the next available cp-state slot for this agent type.

    Returns None if the primary slot is free (not existing or not running).
    Otherwise returns the smallest integer N >= 2 for which
    cp-state-<agent>-N.json is free.
    """
    primary = _cp_file(spec_id, agent)
    if not _is_running(primary):
        return None
    i = 2
    while True:
        candidate = _cp_file(spec_id, agent, i)
        if not _is_running(candidate):
            return i
        i += 1


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
    with _slot_lock(path):
        _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


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


def _bump_and_reset(payload):
    """P2 ba-spec-20260427-194324: increment generation, reset all
    checkpoints to pending, clear waived_reason, refresh updated_at on
    every checkpoint AND on the cp-state-level marker."""
    now = _now_iso_z()
    payload["generation"] = int(payload.get("generation", 1)) + 1
    payload["updated_at"] = now
    for cp in payload.get("checkpoints", []):
        cp["state"] = "pending"
        cp["waived_reason"] = None
        cp["updated_at"] = now


def _check_in_rmw(args, instance_id):
    """Read-modify-write the cp-state file under the slot lock so concurrent
    --bump-generation invocations cannot tear (AC10d). Writes through
    _atomic_write_text directly: _write_payload would take the slot lock a second time."""
    path = _cp_file(args.spec_id, args.agent, instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _slot_lock(path):
        payload = _read_payload(args.spec_id, args.agent, instance_id)
        _stamp_runtime(payload, args, instance_id)
        if getattr(args, "bump_generation", False):
            _bump_and_reset(payload)
        _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


_NO_OWNED_IDLE = object()  # D2 sentinel: "no idle slot recorded for this id" (distinct from "primary")


def _find_owned_idle_slot(spec_id, agent, agent_id):
    """D2 (check-in owner affinity): first NON-running slot (primary first, then
    numbered ascending) whose non-empty recorded agent_id equals agent_id.
    Returns _NO_OWNED_IDLE when there is no such slot (including when agent_id is
    falsy: a falsy id is never an owner). Pure read; does not create any file."""
    wanted = str(agent_id or "").strip()
    if not wanted:
        return _NO_OWNED_IDLE
    for iid, _path in _all_instance_files(spec_id, agent):
        payload = _read_payload(spec_id, agent, iid)
        if payload.get("is_running"):
            continue
        current = str(payload.get("agent_id") or "").strip()
        if current and current == wanted:
            return iid
    return _NO_OWNED_IDLE


def _pick_check_in_slot(args):
    # --bump-generation is an explicit re-split on the primary slot; it does
    # NOT auto-allocate a numbered slot (AC10d invariant: parallel bumps
    # target the same slot to compose serially under the file lock).
    if getattr(args, "bump_generation", False):
        return None
    # D2: re-open the idle slot already recorded for this caller before
    # allocating a fresh one, so the caller's id ends on exactly one slot
    # instead of a stray primary or a wrong idle slot (measured E3-A, E3-A2,
    # E3-C, E7). A caller owning no idle slot keeps the byte-identical
    # fallback (_allocate_instance_id).
    found = _find_owned_idle_slot(args.spec_id, args.agent, args.agent_id)
    if found is not _NO_OWNED_IDLE:
        return found
    return _allocate_instance_id(args.spec_id, args.agent)


def _cmd_check_in(args):
    if not _validate_agent(args.agent):
        return 1
    instance_id = _pick_check_in_slot(args)
    _check_in_rmw(args, instance_id)
    path = _cp_file(args.spec_id, args.agent, instance_id)
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


def _own_slot_hint(agent="<role>"):
    """Self-correction text shared by every refusal that traces back to a missing agent id."""
    return (
        "Self-correct: pass --agent-id with the agent id stored in your own slot file "
        f"(<project>/.claude/specs/<spec-id>/cp-state-{agent}[-N].json, field agent_id). "
        "If your role has several slots, the primary file may hold the spec lead's placeholder id "
        f"(spec-<spec-id>-preregister-{agent}); that id is not yours. Your own slot is the running "
        "one the read-trigger stamped when you first Read your cp-state file: the one whose "
        "checked_in_at is that moment."
    )


def _refuse_blank_agent_id(args):
    """Return 2 after naming cause and fix when a parsed --agent-id is blank, else None.

    Keyed on the parsed value (covers check-in --bump-generation); reads and writes no file.
    """
    agent_id = getattr(args, "agent_id", None)
    if agent_id is None or agent_id.strip():
        return None
    owner_note = ("check-in stamps the given id as the slot owner, so it must not be empty. "
                  if args.cmd == "check-in" else "")
    sys.stderr.write(
        f"ERROR: {args.cmd} refused: --agent-id is empty. The value is empty because the shell "
        "variable that supplies it ($CLAUDE_AGENT_ID) is unset in this shell. Nothing was "
        f"written. {owner_note}{_own_slot_hint(getattr(args, 'agent', None) or '<role>')}\n"
    )
    return 2


def _id_less_target_is_ambiguous(spec_id, agent):
    """Return why an id-less mark/waive cannot pick a slot safely, else None.

    Two limbs: the role has more than one slot file, or its only slot file is running
    for a recorded owner. Any other id-less call keeps the legacy primary-slot path.
    """
    slots = _all_instance_files(spec_id, agent)
    if len(slots) > 1:
        return f"role '{agent}' has {len(slots)} slot files"
    if slots:
        slot = _read_payload(spec_id, agent, slots[0][0])
        owner = str(slot.get("agent_id") or "").strip()
        if owner and slot.get("is_running"):
            return f"role '{agent}' has a running slot owned by agent_id '{owner}'"
    return None


def _resolve_payload_for_actor(spec_id, agent, instance_id, agent_id, op_label):
    """Return (instance_id, payload) for an operation performed by agent_id.

    If --agent-id is supplied, it is authoritative: locate the cp-state slot
    whose stored agent_id matches it. This makes parallel same-role slots safe
    even when the subagent only knows the primary cp-state filename from the
    prompt. If --instance-id is also supplied, validate that the addressed slot
    belongs to the supplied agent_id.

    If --agent-id is omitted, preserve legacy primary-slot behavior for
    read-only/manual workflows, except check-out uses a stricter wrapper below and
    mark/waive refuse when _id_less_target_is_ambiguous finds the target ambiguous.
    """
    if instance_id is not None:
        payload = _read_payload(spec_id, agent, instance_id)
        current = payload.get("agent_id")
        if agent_id and current and current != agent_id:
            first_line = (
                f"ERROR: {op_label} ownership mismatch: slot instance-id="
                f"{instance_id} belongs to agent_id '{current}', not "
                f"'{agent_id}'"
            )
            if op_label in ("mark", "waive") and _closed(payload):
                sys.stderr.write(
                    first_line + "\n"
                    f"cp-state lifecycle closed at {payload['checked_out_at']}; refusing mutation.\n"
                    f"{_non_owner_remedy_line()}\n"
                )
            else:
                sys.stderr.write(first_line + "\n")
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
            first_line = (
                f"ERROR: {op_label} ambiguous: agent_id '{agent_id}' "
                f"matches {len(matches)} cp-state slots for role '{agent}'"
            )
            if op_label in ("mark", "waive"):
                lines = [first_line]
                for m_iid, m_payload in matches:
                    label = "primary" if m_iid is None else f"instance-id={m_iid}"
                    if _closed(m_payload):
                        lines.append(f"  {label}: closed at {m_payload.get('checked_out_at')}")
                    else:
                        lines.append(f"  {label}: running")
                lines.append(
                    "Remedy: pass --instance-id N to select one of the matched "
                    "slots listed above (or run status to see them)."
                )
                sys.stderr.write("\n".join(lines) + "\n")
            else:
                sys.stderr.write(first_line + "\n")
            return None, None
        first_line = (
            f"ERROR: {op_label} forbidden: no cp-state slot for role "
            f"'{agent}' is owned by agent_id '{agent_id}'"
        )
        if op_label in ("mark", "waive"):
            lines = [
                first_line,
                "Cause: this id was never registered for this role, or it was "
                "re-bound to a different slot (check-in or the read-trigger hook "
                "can do that), or its slot's owner was cleared by check-out or "
                "unlock.",
            ]
            slots = _all_instance_files(spec_id, agent)
            if slots:
                lines.append(f"Role '{agent}' slots:")
                for s_iid, _s_path in slots:
                    s_payload = _read_payload(spec_id, agent, s_iid)
                    s_label = "primary" if s_iid is None else f"instance-id={s_iid}"
                    if _closed(s_payload):
                        lines.append(f"  {s_label}: closed at {s_payload.get('checked_out_at')}")
                    elif s_payload.get("is_running"):
                        lines.append(f"  {s_label}: running")
                    else:
                        lines.append(f"  {s_label}: idle")
            lines.append(_non_owner_remedy_line())
            sys.stderr.write("\n".join(lines) + "\n")
        else:
            sys.stderr.write(first_line + "\n")
        return None, None

    why = _id_less_target_is_ambiguous(spec_id, agent) if op_label in ("mark", "waive") else None
    if why:
        sys.stderr.write(
            f"ERROR: {op_label} refused: neither --agent-id nor --instance-id was given and {why}, "
            f"so the target slot is ambiguous. Nothing was written. --instance-id N addresses a "
            f"numbered slot. {_own_slot_hint(agent)}\n"
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


def _closed(payload):
    """Closed means not is_running and checked_out_at (unchanged definition)."""
    return not payload.get("is_running") and bool(payload.get("checked_out_at"))


def _closed_caller_kind(payload, agent_id):
    """Classify a caller against an ALREADY-CLOSED, ALREADY-RESOLVED slot (the
    resolver above has already refused an id bound to no slot, an id bound to
    more than one slot, and an --instance-id mismatch against a non-empty
    owner). The only shapes that reach here are: "owner" (non-empty agent_id
    equal to the slot's own non-empty agent_id), "cleared" (caller supplied an
    id but the slot's recorded owner was cleared by check-out or unlock, only
    reachable via --instance-id), and "id_less" (caller supplied no
    --agent-id at all; a falsy id is never an owner)."""
    caller = str(agent_id or "").strip()
    if not caller:
        return "id_less"
    current = str(payload.get("agent_id") or "").strip()
    if current and caller == current:
        return "owner"
    return "cleared"


def _owner_remedy_line(spec_id, agent, agent_id):
    return (
        f"Remedy: check-in --spec-id {spec_id} --agent {agent} --agent-id {agent_id} "
        "re-opens your own slot (checkpoint states are kept, you stay its owner, "
        "the output names the slot). Do not use --bump-generation: it resets "
        "every checkpoint to pending."
    )


def _status_remedy_line(spec_id, agent):
    return (
        f"Remedy: status --spec-id {spec_id} --agent {agent} shows the "
        "checkpoints this slot actually has."
    )


def _cleared_owner_remedy_line(spec_id, agent):
    return (
        f"Remedy: check-in --spec-id {spec_id} --agent {agent} --agent-id <your id> "
        "re-opens the first idle slot of the role (it need not be this slot; the "
        "output names it) and takes over that slot; its previous owner, if any, "
        "then fails as no-slot. Do not use --bump-generation: it resets every "
        "checkpoint to pending."
    )


def _non_owner_remedy_line():
    return (
        "Remedy: this slot is not yours. Pass --agent-id with the agent_id "
        "stored in your own slot file. check-in with an id that owns no slot "
        "takes over the first idle slot of the role, and its previous owner "
        "loses it."
    )


def _closed_slot_refusal(checked_out_at, reason, remedy_line):
    """F8 replacement: the closed-slot refusal shape shared by every cause
    (owner: pending/unknown/waive; cleared owner; id-less caller). Always rc 1,
    always names the closing time, always carries a Reason: and a Remedy: line."""
    return (
        f"ERROR: cp-state lifecycle closed at {checked_out_at}; refusing mutation.\n"
        f"Reason: {reason}\n"
        f"{remedy_line}\n"
    )


def _refuse_non_owner_closed(payload, kind, spec_id, agent):
    """Non-owner (cleared or id-less) mutation attempt on a closed slot: mark's
    pending/not-found/waive-refusal branches never run for these callers."""
    if kind == "cleared":
        reason = "this slot's recorded owner was cleared by check-out or unlock."
        remedy = _cleared_owner_remedy_line(spec_id, agent)
    else:  # id_less
        reason = "no --agent-id was given; ownership of this closed slot cannot be confirmed."
        remedy = _non_owner_remedy_line()
    sys.stderr.write(_closed_slot_refusal(payload["checked_out_at"], reason, remedy))


def _append_waived_audit(cp, actor, now_iso, after_close_at=None):
    """F6: preserve waiver context per AC4 minimum-keys schema. When
    after_close_at is given (an owner amendment on a closed slot, AC2), the
    entry also records after_close: true and slot_closed_at: after_close_at;
    an open-slot upgrade (after_close_at=None) keeps exactly the six original
    keys, unchanged from the baseline."""
    entry = {
        "prior_state": "waived-with-reason", "prior_waived_reason": cp.get("waived_reason"),
        "prior_updated_at": cp.get("updated_at"), "transitioned_to": "done",
        "transitioned_at": now_iso, "actor": actor,
    }
    if after_close_at is not None:
        entry["after_close"] = True
        entry["slot_closed_at"] = after_close_at
    cp.setdefault("audit_history", []).append(entry)


def _apply_mark_transition(cp, cp_id, actor, after_close_at=None):
    """F5/F6: idempotent re-mark + waiver-audit preservation. Returns: 0=already-done, 1=transition.
    after_close_at is None for every open-slot call (unchanged behavior); the
    closed-slot owner-amendment path (AC2) passes the slot's checked_out_at so
    the audit entry records after_close and slot_closed_at."""
    if cp.get("state") == "done":  # F5/AC3: idempotent re-mark, exact wording
        sys.stderr.write(f"{cp_id} already done at {cp.get('updated_at')}\n")
        return 0
    now = _now_iso_z()
    if cp.get("state") == "waived-with-reason":  # F6: audit before clearing (uses prior updated_at)
        _append_waived_audit(cp, actor, now, after_close_at=after_close_at)
    cp["state"] = "done"
    cp["waived_reason"] = None
    cp["updated_at"] = now
    return 1


def _cmd_mark_on_closed_slot(args, payload, iid, agent_id):
    """Closed-slot mark: owner idempotent-done (no write), owner waived-to-done
    amendment (after_close audit, single write via _write_payload_with_auto_checkout),
    every other mutation refused with cause and remedy (no write). Single write
    site; refuse/no-op paths return before any write."""
    kind = _closed_caller_kind(payload, agent_id)
    if kind != "owner":
        _refuse_non_owner_closed(payload, kind, args.spec_id, args.agent)
        return 1
    cp = _find_cp(payload, args.cp_id)
    if cp is None:
        sys.stderr.write(_closed_slot_refusal(
            payload["checked_out_at"],
            f"cp-id '{args.cp_id}' not found in this slot.",
            _status_remedy_line(args.spec_id, args.agent),
        ))
        return 1
    if cp.get("state") == "pending":
        sys.stderr.write(_closed_slot_refusal(
            payload["checked_out_at"],
            "pending checkpoints cannot be marked done on a closed slot.",
            _owner_remedy_line(args.spec_id, args.agent, agent_id),
        ))
        return 1
    rc_t = _apply_mark_transition(cp, args.cp_id, agent_id, after_close_at=payload["checked_out_at"])
    if rc_t == 0:
        return 0  # idempotent repeat of a done mark: no write, file stays byte-identical
    _write_payload_with_auto_checkout(args.spec_id, args.agent, payload, iid)
    print(
        f"marked done: {args.cp_id} (after-close amendment; slot closed at "
        f"{payload['checked_out_at']} stays closed)"
    )
    return 0


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
    if payload is None:
        return 1
    agent_id = getattr(args, "agent_id", None)
    if _closed(payload):
        return _cmd_mark_on_closed_slot(args, payload, iid, agent_id)
    cp = _find_cp(payload, args.cp_id)
    if cp is None:
        sys.stderr.write(f"ERROR: cp-id '{args.cp_id}' not found\n")
        return 1
    rc_t = _apply_mark_transition(cp, args.cp_id, agent_id)
    if rc_t == 0 and not (payload.get("is_running") and _all_cps_terminal(payload)):
        # D1: idempotent repeat on an open slot that still holds a pending or
        # waived checkpoint (not about to auto-close): no write, matching the
        # closed-slot no-write path.
        return 0
    _write_payload_with_auto_checkout(args.spec_id, args.agent, payload, iid)
    if rc_t == 0:
        return 0
    print(f"marked done: {args.cp_id}")
    return 0


def _refuse_waive_closed(payload, agent_id, spec_id, agent):
    """Waive is refused on every closed slot regardless of checkpoint state or
    caller (design table row 'closed | anyone | waive'). N4: a non-owner or
    id-less caller sees its own cause first (cleared / no --agent-id); only the
    recorded owner sees 'waive is refused on a closed slot'."""
    kind = _closed_caller_kind(payload, agent_id)
    if kind == "cleared":
        reason = "this slot's recorded owner was cleared by check-out or unlock."
        remedy = _cleared_owner_remedy_line(spec_id, agent)
    elif kind == "id_less":
        reason = "no --agent-id was given; ownership of this closed slot cannot be confirmed."
        remedy = _non_owner_remedy_line()
    else:  # owner
        reason = "waive is refused on a closed slot."
        remedy = _owner_remedy_line(spec_id, agent, agent_id)
    sys.stderr.write(_closed_slot_refusal(payload["checked_out_at"], reason, remedy))


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
    if payload is None:
        return 1
    agent_id = getattr(args, "agent_id", None)
    if _closed(payload):
        _refuse_waive_closed(payload, agent_id, args.spec_id, args.agent)
        return 1
    cp = _find_cp(payload, args.cp_id)
    if cp is None:
        sys.stderr.write(f"ERROR: cp-id '{args.cp_id}' not found\n")
        return 1
    actor = agent_id or "unknown"
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


class _CauseNamingParser(argparse.ArgumentParser):
    """Adds cause and fix to the argparse error an unquoted, unset $CLAUDE_AGENT_ID produces."""

    def error(self, message):
        if "--agent-id" in message and "expected one argument" in message:
            message += (
                ". The value is missing because the shell variable that supplies it "
                "($CLAUDE_AGENT_ID) is unset and was left unquoted. Nothing was written. "
                + _own_slot_hint()
            )
        super().error(message)


def _parse_args():
    p = _CauseNamingParser(description="Write cp-state files (only legal writer).")
    sub = p.add_subparsers(dest="cmd", required=True)

    _add_check_in_cmd(sub)
    _add_mark_cmd(sub)
    _add_waive_cmd(sub)
    _add_status_cmd(sub)
    _add_check_out_cmd(sub)
    _add_unlock_cmd(sub)

    return p.parse_args()


def _add_check_in_cmd(sub):
    sp = sub.add_parser(
        "check-in",
        help="Register subagent as running against a spec",
        description=(
            "Register the caller as running against a spec. On a closed slot "
            "this re-opens it: checkpoint states are kept and ownership is "
            "re-bound to --agent-id. The idle slot already recorded for "
            "--agent-id is re-opened first, else the first idle slot of the "
            "role. Use this, not --bump-generation, to continue after a "
            "lifecycle-closed refusal."
        ),
    )
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--artifact", default=None)
    sp.add_argument("--bump-generation", dest="bump_generation",
                    action="store_true", default=False)


def _add_mark_cmd(sub):
    sp = sub.add_parser(
        "mark",
        help="Mark a checkpoint as done",
        description=(
            "Mark a checkpoint done. Idempotent: repeating a done mark "
            "succeeds and changes no checkpoint; on a closed slot nothing is "
            "written. An open slot whose checkpoints are all terminal still "
            "closes on the repeat (see the module docstring). On a closed "
            "slot only the recorded owner may repeat a done mark or upgrade "
            "a waived-with-reason checkpoint to done (audited as "
            "after_close; the slot stays closed); every other mutation on a "
            "closed slot exits 1 with the closing time and a remedy."
        ),
    )
    sp.add_argument("--spec-id", required=True)
    sp.add_argument("--agent", required=True)
    sp.add_argument("--instance-id", type=int, default=None)
    sp.add_argument("--agent-id", default=None)
    sp.add_argument("--cp-id", required=True)


def _add_waive_cmd(sub):
    sp = sub.add_parser(
        "waive",
        help="Waive a checkpoint (auto-text records actor + ISO timestamp)",
        description=(
            "Waive a checkpoint (auto-text records actor + ISO timestamp). "
            "Refused (exit 1) on a closed slot; re-open the slot with "
            "check-in first."
        ),
    )
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


def _lock_plan(args):
    """Return (take_lock, create_spec_dir). The directory lock is taken only for a command known
    to be valid (a known role) and only when the spec directory exists or the command creates it
    anyway (check-in; check-out without --agent-id), so a refused command or a mistyped spec id
    leaves the tree as it was. status is read-only and takes no lock."""
    if args.cmd in READ_ONLY_COMMANDS:
        return False, False
    agent = getattr(args, "agent", None)
    if agent is not None and agent not in ALLOWED_AGENTS:
        return False, False
    creates = args.cmd == "check-in" or (args.cmd == "check-out" and not getattr(args, "agent_id", None))
    return (creates or _cp_dir(args.spec_id).is_dir()), creates


def main():
    args = _parse_args()
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        sys.stderr.write(f"ERROR: unknown command '{args.cmd}'\n")
        return 1
    blank_rc = _refuse_blank_agent_id(args)
    if blank_rc is not None:
        return blank_rc
    take_lock, create = _lock_plan(args)
    try:
        if not take_lock:
            return handler(args)
        with _spec_dir_lock(_cp_dir(args.spec_id), create):
            return handler(args)
    except LockTimeout as exc:
        sys.stderr.write(
            f"ERROR: timed out after {exc.seconds:g}s waiting for {exc.label}; another spec-check.py "
            f"or the read-trigger hook holds it. This is retryable: run the same command again. "
            f"The slot being waited for was not changed (exit {EXIT_LOCK_TIMEOUT}).\n"
        )
        return EXIT_LOCK_TIMEOUT
    except SpecCheckIOError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
