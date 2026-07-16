#!/usr/bin/env python3
"""PreToolUse Hook (Read): Auto-register subagent into cp-state on direct
cp-state file read.

Triggers when a subagent's `Read` tool call targets either of:

    <project>/.claude/specs/<spec-id>/cp-state-<agent>(-N).json
    <project>/.claude/dev-registry/<sid>/<agent>.json

The first pattern is the SECOND ACTION protocol mandated by /spec, /dev,
/dev-command, /dev-overnight, and /close. The second pattern is the
dev-registry sentinel for /dev workflows (no spec views).

P1 tombstone (ba-spec-20260427-194324, dev cycle 20260427-194324):
The legacy view-file trigger (VIEW_PATH_PATTERN matching
docs/dev/specs/<spec-id>/views/<agent>.md + _handle_spec_view +
_extract_target) was REMOVED on 2026-04-27 because Anthropic built-in
Explore subagents incidentally read view files for codebase research and
were getting falsely registered into cp-state. The SECOND ACTION protocol
already covers all legitimate registration via direct cp-state Read; the
view-file trigger was structurally redundant AND structurally unsafe. DO
NOT REINTRODUCE IT under any guise (Codex Q7).

Fail-open: any error -> exit 0. Never block on unexpected input.
"""

import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# Dev-registry sentinel: sibling mechanism for /dev, /dev-command, /dev-overnight
# workflows. These workflows produce no spec views, so VIEW_PATH_PATTERN never
# fires for them. Root cause: commit e086ccb scoped enforcement to /spec only;
# /dev sessions have no cp-state files, so the enforcement hook fails open.
# Fix: orchestrators write .claude/dev-registry/<session_id>/<agent>.json
# sentinels; subagents read them as FIRST ACTION; this hook extracts the agent
# type from the path and writes the Claude-stdin agent_id -> agent_type mapping
# to .claude/dev-registry/agent-index.json. See ba-spec-20260424-110000.md.
DEV_SENTINEL_PATTERN = re.compile(
    r".*/\.claude/dev-registry/(?P<session_id>[^/]+)/(?P<agent>[^/]+)\.json$"
)

# CP-STATE direct-read pattern: subagents per /root/.claude/commands/dev.md
# SECOND ACTION blocks read .claude/specs/<spec-id>/cp-state-<agent>(-N).json
# directly to register their agent_id. The original VIEW_PATH_PATTERN only
# matched docs/dev/specs/<spec-id>/views/<agent>.md, so cp-state direct reads
# never triggered check-in. This pattern covers BOTH primary slot files
# (cp-state-<agent>.json) and numbered instance slots
# (cp-state-<agent>-<N>.json, N>=2). Mirrors _CP_STATE_FILENAME_RE in
# /root/.claude/scripts/spec-check.py (which is the writer).
CP_STATE_PATH_PATTERN = re.compile(
    r".*/\.claude/specs/(?P<spec_id>[^/]+)/cp-state-(?P<agent>[A-Za-z0-9_-]+?)(?:-\d+)?\.json$"
)

CP_AGENTS = {
    # Core /spec, /dev, and /dev-overnight roles.
    "architect", "ba", "dev", "pm", "product-owner", "qa",
    "ui-specialist", "user",
    # Command/overnight specialist roles.  They share the same cp-state
    # lifecycle as the core roles: direct cp-state Read -> check-in ->
    # subagent Stop blocks until all checkpoints are done/waived.
    "cleaner", "cleanliness-inspector", "git-edge-case-analyst",
    "prompt-inspector", "rule-inspector", "spec", "style-inspector",
    "test-executor", "test-validator",
    # Test-writer agent (spec-20260518-225715 §5.2): generates pytest
    # skeletons from BA-produced acceptance-criteria JSON between BA and Dev.
    "test-writer",
    # Graphify enrichment subagent (spec-20260527-061433): runs at Step 7.5
    # after BA-QA validation, before DEV.  Registered here alongside
    # ALLOWED_AGENTS (scripts/spec-check.py) and agent_types
    # (hooks/prompt-workflow.py) per arch-2 precedent (test-writer pattern).
    "graphify",
    # Agentic commit role.
    "changelog-analyst",
    # Agentic git workflow analyst roles (push, merge, pull).
    "push-analyst", "merge-analyst", "pull-analyst",
}

# Dev-registry sentinel agent names must match CP_AGENTS.  Keeping a single
# source of truth prevents the historic split where a role could register for
# code-write policy but not for checkpoint-stop enforcement (or the reverse).
DEV_REGISTRY_AGENTS = CP_AGENTS


# Slot filename pattern: cp-state-<agent>.json (primary)
#                    or  cp-state-<agent>-<N>.json (numbered, N>=2, auto-allocated
#                        by spec-check.py when the primary is held by a running
#                        instance). See /root/.claude/scripts/spec-check.py for the writer.


def _now_iso_z():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_cp_state_target(data):
    """Extract (spec_id, agent) for a Read targeting a cp-state file directly.

    Returns (None, None) when the Read does not match the cp-state path or
    the agent name is not in CP_AGENTS. Mirrors the agent-name validation
    used by _extract_dev_sentinel to prevent arbitrary path reads from
    triggering registration.
    """
    if not isinstance(data, dict):
        return None, None
    if data.get("tool_name") != "Read":
        return None, None
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    m = CP_STATE_PATH_PATTERN.match(file_path)
    if not m:
        return None, None
    agent = m.group("agent")
    if agent not in CP_AGENTS:
        return None, None
    return m.group("spec_id"), agent


def _extract_dev_sentinel(data):
    """Extract (session_id, agent) for a Read targeting the dev-registry.

    Returns (None, None) when the Read does not match the sentinel path or the
    agent name is not in DEV_REGISTRY_AGENTS. Validating the agent name here
    prevents arbitrary JSON reads from being written into the index.
    """
    if not isinstance(data, dict):
        return None, None
    if data.get("tool_name") != "Read":
        return None, None
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    m = DEV_SENTINEL_PATTERN.match(file_path)
    if not m:
        return None, None
    agent = m.group("agent")
    if agent not in DEV_REGISTRY_AGENTS:
        return None, None
    return m.group("session_id"), agent


def _dev_registry_index_path(project_dir):
    return Path(project_dir) / ".claude" / "dev-registry" / "agent-index.json"


def _read_index(index_path):
    """Load agent-index.json as dict, returning {} on any error."""
    try:
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return existing if isinstance(existing, dict) else {}


def _write_index_locked(index_path, agent_id, agent_type, dev_session_id=None):
    """Write the merged mapping while holding fcntl.LOCK_EX on a sibling lock."""
    lock_path = index_path.with_suffix(index_path.suffix + ".lock")
    with open(lock_path, "w") as lh:
        fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
        existing = _read_index(index_path)
        existing[agent_id] = {"agent_type": agent_type, "dev_session_id": dev_session_id} if dev_session_id else agent_type
        index_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        fcntl.flock(lh.fileno(), fcntl.LOCK_UN)


def _update_dev_registry_index(project_dir, agent_id, agent_type, dev_session_id=None):
    """Append {agent_id: agent_type} to agent-index.json under fcntl.LOCK_EX.

    Fails silent (returns False) on I/O errors so the hook remains fail-open.
    """
    index_path = _dev_registry_index_path(project_dir)
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        _write_index_locked(index_path, agent_id, agent_type, dev_session_id)
    except OSError:
        return False
    return True


def _cp_dir(project_dir, spec_id):
    return Path(project_dir) / ".claude" / "specs" / spec_id


def _all_cp_files(project_dir, spec_id, agent):
    """Return every cp-state slot file for (spec, agent): primary + numbered.

    Primary (cp-state-<agent>.json) first, then numbered slots in ascending
    integer order (cp-state-<agent>-2.json, -3.json, ...). Mirrors the
    allocation policy in /root/.claude/scripts/spec-check.py.
    """
    cp_dir = _cp_dir(project_dir, spec_id)
    if not cp_dir.exists():
        return []
    files = []
    primary = cp_dir / f"cp-state-{agent}.json"
    if primary.exists():
        files.append(primary)
    pattern = re.compile(rf"^cp-state-{re.escape(agent)}-(\d+)\.json$")
    numbered = []
    for child in cp_dir.iterdir():
        m = pattern.match(child.name)
        if m:
            numbered.append((int(m.group(1)), child))
    numbered.sort(key=lambda pair: pair[0])
    files.extend(p for _, p in numbered)
    return files


def _read_payload(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cp_checkin_dir_lock_path(cp_dir):
    """Return the dir-level lock path used by FINDING-6 to serialize
    read-pick-write windows for parallel agent registrations against the
    same (spec, agent) pair. Sibling to the cp-state files inside cp_dir.
    """
    return cp_dir / ".cp-checkin.lock"


def _open_dir_lock(cp_dir):
    """Open and EX-lock the dir-level checkin lock. Caller must close the
    returned file handle to release. Returns None on any I/O error so the
    caller can fall through to fail-open behavior.
    """
    try:
        cp_dir.mkdir(parents=True, exist_ok=True)
        lock_path = _cp_checkin_dir_lock_path(cp_dir)
        lh = open(lock_path, "w")
    except OSError:
        return None
    try:
        fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
    except OSError:
        lh.close()
        return None
    return lh


def _release_dir_lock(lh):
    if lh is None:
        return
    try:
        fcntl.flock(lh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lh.close()
    except OSError:
        pass


def _write_payload(path, payload):
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lh:
        fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        fcntl.flock(lh.fileno(), fcntl.LOCK_UN)


def _update_payload(payload, agent_id):
    """Restamp ONLY runtime ownership fields. Never reset checkpoint state.

    P2 contract (ba-spec-20260427-194324): the hook is a takeover-stamper,
    not a generation gate. Default takeover preserves every existing
    `state` and `waived_reason` on every checkpoint. The ONLY path that
    resets checkpoints is the explicit writer path
    `spec-check.py check-in --bump-generation` (Codex Q2: PreToolUse
    payloads are not authoritative enough to drive a generation reset).

    Legacy back-fill: if the on-disk file lacks the `generation` field, do
    NOT silently introduce it here -- that would obscure migration intent.
    Newly-created cp-state files initialize `generation=1` via
    spec-check.py's _default_payload.

    STALE-1 (2026-07-15, Codex adversarial review finding (a)): only
    refresh checked_in_at on a genuine new claim (transition from idle, or
    a different agent_id taking over). A repeat Read by the SAME
    already-registered owner of an already-running slot must NOT restamp
    checked_in_at -- otherwise a bystander session that incidentally
    re-reads a cp-state path it auto-registered into (e.g. while debugging)
    could keep that registration perpetually "fresh", defeating
    agent_resolver.py's staleness bound (hooks/lib/agent_resolver.py
    _MAX_ACTIVE_AGE_SECONDS) indefinitely.
    """
    already_claimed_by_same_owner = bool(payload.get("is_running")) and bool(agent_id) and payload.get("agent_id") == agent_id
    payload["is_running"] = True
    if agent_id:
        payload["agent_id"] = agent_id
    if not already_claimed_by_same_owner:
        payload["checked_in_at"] = _now_iso_z()
    payload["checked_out_at"] = None
    return payload


def _load_slots(files):
    loaded = []
    for p in files:
        payload = _read_payload(p)
        if payload is not None:
            loaded.append((p, payload))
    return loaded


def _match_by_agent_id(loaded, agent_id):
    if not agent_id:
        return None
    for p, payload in loaded:
        if payload.get("agent_id") == agent_id:
            return p, payload
    return None


def _first_idle_slot(loaded):
    for p, payload in loaded:
        if not payload.get("is_running"):
            return p, payload
    return None


def _pick_slot(files, agent_id):
    """Choose which cp-state slot this Read belongs to.

    1. If agent_id is present, prefer a slot whose stored agent_id matches
       (unambiguous pin for parallel instances of the same agent type).
    2. Otherwise, prefer the first slot that is NOT is_running (the slot
       that will transition to running via this Read).
    3. Otherwise, report no reusable slot. The caller may allocate a numbered
       slot for true parallel same-role runs instead of hijacking a running
       sibling.

    Returns (path, payload) or (None, None).
    """
    loaded = _load_slots(files)
    if not loaded:
        return None, None
    pinned = _match_by_agent_id(loaded, agent_id)
    if pinned is not None:
        return pinned
    idle = _first_idle_slot(loaded)
    if idle is not None:
        return idle
    if agent_id:
        return None, None
    return loaded[0] if loaded else (None, None)


def _next_numbered_slot(cp_dir, agent):
    i = 2
    while True:
        candidate = cp_dir / f"cp-state-{agent}-{i}.json"
        if not candidate.exists():
            return i, candidate
        i += 1


def _clone_payload_for_parallel_slot(template, agent_id, instance_id):
    payload = json.loads(json.dumps(template))
    payload["instance_id"] = instance_id
    payload["agent_id"] = agent_id
    payload["is_running"] = False
    payload["checked_out_at"] = None
    # _update_payload will set checked_in_at/is_running and reset checkpoints.
    return payload


def _do_pick_and_write(files, agent_id, cp_dir=None, agent=None):
    """Helper held under the dir-lock: pick a slot and write the updated
    payload. Returns True iff the write happened.
    """
    path, payload = _pick_slot(files, agent_id)
    if (path is None or payload is None) and agent_id and files and cp_dir and agent:
        template = _read_payload(files[0])
        if template is not None:
            instance_id, path = _next_numbered_slot(cp_dir, agent)
            payload = _clone_payload_for_parallel_slot(template, agent_id, instance_id)
    if path is None or payload is None:
        return False
    payload = _update_payload(payload, agent_id)
    _write_payload(path, payload)
    return True


def _checkin_under_lock(project_dir, spec_id, agent, data):
    """FINDING-6: hold a dir-level fcntl.LOCK_EX across pick + write.

    The shared lock file at <cp_dir>/.cp-checkin.lock serializes parallel
    agent registrations for the same (spec, agent) pair so two concurrent
    pretool-cp-checkin invocations cannot both pick the same idle slot.

    Returns True when the slot was picked and written; False when the
    cp_dir is missing, no slot is available, or the lock could not be
    acquired (fail-open on lock failure: the slot still gets the per-file
    fcntl in _write_payload, just without the wider read-pick-write
    serialization).
    """
    cp_dir = _cp_dir(project_dir, spec_id)
    if not cp_dir.exists():
        return False
    files = _all_cp_files(project_dir, spec_id, agent)
    if not files:
        return False
    agent_id = data.get("agent_id")
    lh = _open_dir_lock(cp_dir)
    try:
        return _do_pick_and_write(files, agent_id, cp_dir, agent)
    finally:
        _release_dir_lock(lh)


def _handle_cp_state_direct_read(data, project_dir):
    """Process a CP_STATE_PATH_PATTERN Read; update the matching cp-state slot.

    Treats a direct Read of .claude/specs/<spec-id>/cp-state-<agent>(-N).json
    as the SECOND ACTION registration trigger: slot pick by agent_id, mark
    is_running=true, write locked. Returns True when handled, False when the
    Read does not target a cp-state file or no cp-state exists for the
    (spec_id, agent) pair.

    BUG-CPSTATE-1: the SECOND ACTION blocks in /root/.claude/commands/dev.md
    instruct subagents to Read cp-state files directly; without this handler
    the agent_id was never registered.

    FINDING-6: the read-pick-write window is held under a dir-level
    fcntl.LOCK_EX on .cp-checkin.lock so two parallel cp-state reads against
    the same (spec, agent) pair cannot pick the same idle slot and clobber.
    """
    spec_id, agent = _extract_cp_state_target(data)
    if spec_id is None or agent not in CP_AGENTS:
        return False
    return _checkin_under_lock(project_dir, spec_id, agent, data)


def _handle_dev_sentinel(data, project_dir):
    """Process a DEV_SENTINEL_PATTERN Read; register UUID -> agent_type.

    Returns True when handled, False when the Read does not target a sentinel
    or the Claude-stdin agent_id is missing (main-agent Read is ignored).
    """
    session_id, agent = _extract_dev_sentinel(data)
    if session_id is None:
        return False
    agent_id = data.get("agent_id")
    if not agent_id:
        return False
    _update_dev_registry_index(project_dir, agent_id, agent, session_id)
    return True


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    # SECOND ACTION direct cp-state read (the legitimate registration trigger
    # mandated by /spec, /dev, /dev-command, /dev-overnight, /close), then
    # /dev sentinel for /dev workflows without spec views. Both handlers are
    # fail-open: any miss or error -> exit 0. The legacy view-file trigger
    # was removed (see module docstring P1 tombstone).
    if _handle_cp_state_direct_read(data, project_dir):
        sys.exit(0)
    _handle_dev_sentinel(data, project_dir)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
