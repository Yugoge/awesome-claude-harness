#!/usr/bin/env python3
"""Resolve subagent identity to agent_type string: the one role reader.

Refactored from pretool-subagent-code-block.py::_find_agent_type so that
multiple hooks (pretool-subagent-code-block.py, pretool-tool-policy.py,
the overnight guard) share one canonical lookup.

Resolution order (first hit wins), what Claude Code records before any
registry an agent's own reads produce:
  0. No payload.agent_id -> None: the main agent, whatever agent_type says.
  1. payload.agent_type — the CLI names the subagent's type with its agent_id.
  2. agentType of the CLI's agent-<agent_id>.meta.json for the session, in
     every account root (an older CLI with no agent_type in the payload).
  3. payload.agent_id in /spec cp-state files, then in /dev agent-index.json
     (older check-ins; resolve_dev_registry_entry also gives the cycle), then
     in cp-state slots checked in more than a day ago (STALE-1 below).
  4. None — caller decides (unregistered subagent).
A top-level payload.subagent_type is no role (only a dispatch's tool_input has one).

Fail-safe: every I/O path is wrapped; on any unexpected exception we
return None rather than raise.

LOW-10 (2026-05-07): callers MUST NOT hard-block on `None`. Claude Code
may dispatch subagents before any sentinel-creating tool runs, so the
agent-index entry can legitimately be missing during the first write.
The canonical contract is: hard-block on resolved-but-wrong role; for
None, degrade to warn + allow. See pretool-subagent-code-block.py.

STALE-1 (2026-07-15): cp-state files that never got checked out (crashed
session, abandoned spec, orphaned instance slot) sit on disk forever with
is_running=true. Because step 3 of the resolution order scans ALL specs
globally (not just the current session's own spec), a brand-new session
whose agent_id happens to match one of these dangling entries -- via
recycled/reused runtime agent_id values, observed in practice -- was
getting silently misattributed that stale entry's role. Fix: an
is_running=true match is only trusted as "active" (authoritative for
resolution) if checked_in_at is within _MAX_ACTIVE_AGE_SECONDS. Beyond
that window it is treated exactly like an is_running=false match: not
authoritative, caller falls through to agent-index (AC-3 semantics
already established below). This does not touch the agent-index fallback
path itself, only what counts as an authoritative cp-state hit BEFORE it.

STALE-1 residual risk (Codex adversarial review, 2026-07-15): a resolver-
only staleness bound cannot catch a *freshly* manufactured dangling entry
(pretool-cp-checkin.py auto-registers ANY Read of a matching cp-state
path, including incidental/debugging reads, with no way for this module
to distinguish that from a genuine dispatch). Mitigated, not eliminated,
by a companion pretool-cp-checkin.py fix (2026-07-15) that stops
refreshing checked_in_at on repeat reads by an already-registered owner --
so a bogus entry can no longer be kept perpetually "fresh" by the same
bystander re-reading it, and will itself go stale within
_MAX_ACTIVE_AGE_SECONDS of its single registration. (That registration is
now scripts/spec-check.py `register`, which the hook runs.) A freshly-created
bogus entry can still cause misattribution for that same bounded window;
fully closing that gap would require an explicit, ownership-validated
dispatch-claim protocol (out of scope for this fix -- flagged as a
follow-up).

STALE-1 after the owner's ruling of 2026-11-20 (no window refuses or leaves
out by age; it warns and the agent deals with it): a running slot checked in
more than _MAX_ACTIVE_AGE_SECONDS ago is no longer dropped. It still yields to
every fresher record (a fresh slot, then agent-index.json) and is the last
step before None (_stale_role), with a warning naming the slot and its age; a
resumed agent whose /spec slot is a day old keeps its role. The protection
kept is the one age never was the reason for: stale slots of different roles
for one id give no role (_stale_role's docstring).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# STALE-1: upper bound on how long an is_running=true cp-state entry is
# trusted without being re-touched (checked_in_at refreshed by a genuine
# check-in). Originally set to 8h (matching /dev-overnight's documented
# default end-time), but Codex adversarial review (2026-07-15) found real
# on-disk evidence of a legitimate, cleanly-completed single `dev` cp-state
# lifecycle (check-in to auto-checkout-on-all-checkpoints-terminal) lasting
# 10.86h (.claude/specs/20260604-204954/cp-state-dev.json in this harness's
# own history) -- 8h would have false-negatived that genuine session. 24h
# gives >2x margin over the longest such lifecycle observed, while still
# self-healing an order of magnitude faster than the dangling entries this
# fix targets (observed ranging from ~1 day to 2+ months stale).
_MAX_ACTIVE_AGE_SECONDS = 24 * 60 * 60

# STALE-1 Codex (c): a checked_in_at timestamp in the future (clock skew
# between writer/reader, or a corrupt/adversarial entry) makes `age`
# negative; without a floor, `age > max_age_seconds` is never true and the
# entry would be trusted as "fresh" forever (or until far past the future
# instant). Allow a small tolerance for ordinary clock skew; anything
# beyond it is untrusted (stale), not "eternally fresh".
_CLOCK_SKEW_TOLERANCE_SECONDS = 5 * 60


def _checked_in_age_seconds(payload: dict) -> Optional[float]:
    """Seconds since payload['checked_in_at'], or None if missing/unparseable."""
    ts = payload.get("checked_in_at")
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _untrusted_time(payload: dict) -> bool:
    """A check-in time that is missing, unparseable or in the future beyond
    _CLOCK_SKEW_TOLERANCE_SECONDS: no age can be read from it at all, so the
    slot is not trusted (fail-safe: unexpected -> non-authoritative)."""
    age = _checked_in_age_seconds(payload)
    return age is None or age < -_CLOCK_SKEW_TOLERANCE_SECONDS


def cp_state_running(payload: dict) -> bool:
    """The one rule on whether a cp-state slot is running: is_running=true AND
    a check-in time that can be read (_untrusted_time). Its age no longer
    decides (the owner's ruling of 2026-11-20: no window refuses or leaves out
    by age); stale_note names a slot past _MAX_ACTIVE_AGE_SECONDS. Role
    resolution below and subagentstop-cp-enforce.py (a stopping agent's
    pending checkpoints) both take it."""
    return bool(payload.get("is_running")) and not _untrusted_time(payload)


def stale_note(payload: dict, path: str = "") -> str:
    """The warning for a running slot checked in more than _MAX_ACTIVE_AGE_SECONDS
    ago, '' for a fresher one: it names the slot and its age."""
    age = _checked_in_age_seconds(payload)
    if age is None or age <= _MAX_ACTIVE_AGE_SECONDS:
        return ""
    return (f"warning: cp-state slot {path or payload.get('spec_id')} (agent_id {payload.get('agent_id')}, "
            f"role {payload.get('agent_type')}) was checked in {age / 3600:.1f} h ago and never checked out; "
            "it is honoured. If this agent is not that slot's, check it out with scripts/spec-check.py.")


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_match(path: str, agent_id: str) -> Optional[dict]:
    """Return cp-state dict if agent_id matches, else None.

    The full payload, so disambiguation in _scan_cp_state_files can inspect
    is_running and checked_in_at without re-reading the file.
    """
    data = _read_json(path)
    if not data or data.get("agent_id") != agent_id:
        return None
    t = data.get("agent_type")
    if not isinstance(t, str):
        return None
    return data


def _pick_active(matches: list) -> Optional[str]:
    """Disambiguate among is_running=true matches.

    Cross-role active collision -> None (fail closed).
    Same-role active collision -> that agent_type.
    Single active -> its agent_type.
    """
    types = {m.get("agent_type") for m in matches}
    if len(types) > 1:
        return None  # F14 M8: cross-role active collision -> fail closed
    return next(iter(types))  # F14 M9: deterministic same-role active


def resolve_dev_registry_entry(agent_id: str, project_dir: str) -> Optional[dict]:
    """Return a normalized entry dict for agent_id, or None: the one parse of
    agent-index.json (resolve_agent_type's step 3, lib/agent_cycle.py's cycle).

    Always returns {"agent_type": str, "dev_session_id": str|None}.
    Handles both legacy flat-string values (wraps as {"agent_type": value,
    "dev_session_id": None}) and M0 object values (normalizes via .get()
    so missing keys never cause KeyError on malformed entries).
    Returns None when agent_id is absent, agent_type is not a str, or
    any I/O error occurs.
    """
    index_path = f"{project_dir}/.claude/dev-registry/agent-index.json"
    data = _read_json(index_path)
    if not data:
        return None
    value = data.get(agent_id)
    if isinstance(value, str):
        return {"agent_type": value, "dev_session_id": None}
    if isinstance(value, dict):
        t = value.get("agent_type")
        if not isinstance(t, str):
            return None
        return {"agent_type": t, "dev_session_id": value.get("dev_session_id")}
    return None


_FAIL_CLOSED = object()  # sentinel: cross-role active collision -> deny


def _glob_cp_state(project_dir: str) -> list:
    pattern = f"{project_dir}/.claude/specs/*/cp-state-*.json"
    try:
        return glob.glob(pattern)
    except OSError:
        return []


def _scan_cp_state_files(agent_id: str, project_dir: str):
    """Tri-state cp-state scan.

    Returns: agent_type str | _FAIL_CLOSED sentinel | None.
      - str: a single resolved active match (F14 M9)
      - _FAIL_CLOSED: active cross-role collision (F14 M8 fail-closed);
        caller MUST NOT fall through to agent-index.
      - None: no match, inactive-only, or active-but-stale (AC-3 /
        STALE-1 non-authoritative); caller MAY fall through to agent-index.
    """
    paths = _glob_cp_state(project_dir)
    matches = [d for d in (_read_match(p, agent_id) for p in paths) if d]
    # STALE-1: is_running=true alone is not enough -- a dangling entry that
    # was never checked out also has is_running=true forever. Only a fresh
    # match is authoritative here; a stale one is _resolve_by_id's last resort.
    active = [m for m in matches if cp_state_running(m) and not stale_note(m)]
    if not active:
        return None
    picked = _pick_active(active)
    return _FAIL_CLOSED if picked is None else picked


def _stale_role(agent_id: str, project_dir: str) -> Optional[str]:
    """The role of this agent id's running cp-state slots checked in more than
    _MAX_ACTIVE_AGE_SECONDS ago, with a warning on stderr naming each, when they
    all name one role. Asked only where no fresher record names the id: before
    the 2026-11-20 ruling the age dropped them and the caller had no role.

    Entries are keyed by agent_id alone, the CLI's id of one agent (a resumed
    agent keeps it), so such a slot is the caller's own registration; the one
    way it can name another agent's role is an id carried by two agents, or by
    one agent in several roles' slots, which shows as slots of different roles
    (measured 2026-11-20 on the live tree: 3 of 179 ids, all CLI-shaped). That case keeps
    the protection: no role, as for a fresh cross-role collision."""
    hits = [(p, d) for p, d in ((p, _read_match(p, agent_id)) for p in _glob_cp_state(project_dir))
            if d and cp_state_running(d) and stale_note(d)]
    if not hits or len({d.get("agent_type") for _, d in hits}) > 1:
        return None
    for path, data in hits:
        sys.stderr.write(f"agent_resolver: {stale_note(data, path)}\n")
    return hits[0][1].get("agent_type")


def _meta_agent_type(agent_id: str, payload: dict, project_dir: str) -> Optional[str]:
    """Step 2, through the restart path's meta reader, imported only here: a
    payload naming its role pays nothing for it."""
    try:
        from .subagent_restart import SESSION_RE, _metadata_by_tool_use, account_project_roots, project_slug
    except ImportError:  # hooks/lib placed directly on sys.path
        from subagent_restart import SESSION_RE, _metadata_by_tool_use, account_project_roots, project_slug  # type: ignore[no-redef]
    session_id, transcript = payload.get("session_id"), payload.get("transcript_path")
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        return None
    dirs = [Path(transcript).parent] if isinstance(transcript, str) and transcript else []
    for folder in dict.fromkeys(dirs + [root / project_slug(project_dir) for root in account_project_roots()]):
        for meta in _metadata_by_tool_use(folder / f"{session_id}.jsonl").values():
            if meta["agent_id"] == agent_id and meta["agent_type"]:
                return meta["agent_type"]
    return None


def _resolve_by_id(agent_id: str, payload: dict) -> Optional[str]:
    """Steps 2 and 3 of the order."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    try:
        role = _meta_agent_type(agent_id, payload, project_dir)
    except Exception:  # fail-safe (module docstring): an unreadable meta is no meta
        role = None
    if role:
        return role
    spec_hit = _scan_cp_state_files(agent_id, project_dir)
    if spec_hit is _FAIL_CLOSED:
        return None  # active collision: deny, do NOT consult agent-index
    if isinstance(spec_hit, str):
        return spec_hit
    entry = resolve_dev_registry_entry(agent_id, project_dir)
    return entry["agent_type"] if entry else _stale_role(agent_id, project_dir)


def resolve_agent_type(payload: dict) -> Optional[str]:
    """Public API: hook stdin payload -> agent_type or None (the order above)."""
    if not isinstance(payload, dict):
        return None
    agent_id = payload.get("agent_id")
    if not agent_id or not isinstance(agent_id, str):
        return None
    role = payload.get("agent_type")
    if isinstance(role, str) and role:
        return role
    return _resolve_by_id(agent_id, payload)
