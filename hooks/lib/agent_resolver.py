#!/usr/bin/env python3
"""Resolve subagent identity to agent_type string.

Refactored from pretool-subagent-code-block.py::_find_agent_type so that
multiple hooks (pretool-subagent-code-block.py, pretool-tool-policy.py)
can share one canonical lookup.

Resolution order (first hit wins):
  1. payload.subagent_type — if the runtime already injects the role label.
  2. payload.agent_id matched against /spec cp-state files.
  3. payload.agent_id matched against /dev dev-registry agent-index.json.
  4. None — caller decides (main agent or unknown).

Fail-safe: every I/O path is wrapped; on any unexpected exception we
return None rather than raise.

LOW-10 (2026-05-07): callers MUST NOT hard-block on `None`. Claude Code
may dispatch subagents before any sentinel-creating tool runs, so the
agent-index entry can legitimately be missing during the first write.
The canonical contract is: hard-block on resolved-but-wrong role; for
None, degrade to warn + allow. See pretool-subagent-code-block.py.

STALE-1 (2026-07-15): cp-state files that never got checked out (crashed
session, abandoned spec, orphaned instance slot) sit on disk forever with
is_running=true. Because step 2 of the resolution order scans ALL specs
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
_MAX_ACTIVE_AGE_SECONDS of its single registration. A freshly-created
bogus entry can still cause misattribution for that same bounded window;
fully closing that gap would require an explicit, ownership-validated
dispatch-claim protocol (out of scope for this fix -- flagged as a
follow-up).
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
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


def _is_stale(payload: dict, max_age_seconds: float = _MAX_ACTIVE_AGE_SECONDS) -> bool:
    """True iff payload is too old (or suspiciously future-dated) to trust
    as an active resolution hit.

    Fail-safe direction: a missing/unparseable checked_in_at is treated as
    stale (excluded from trust) rather than trusted indefinitely -- mirrors
    the module's existing "unexpected -> None/non-authoritative" ethos.
    """
    age = _checked_in_age_seconds(payload)
    if age is None:
        return True
    if age < -_CLOCK_SKEW_TOLERANCE_SECONDS:
        return True
    return age > max_age_seconds


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _match_cp_state(path: str, agent_id: str) -> Optional[str]:
    data = _read_json(path)
    if not data or data.get("agent_id") != agent_id:
        return None
    t = data.get("agent_type")
    return t if isinstance(t, str) else None


def _read_match(path: str, agent_id: str) -> Optional[dict]:
    """Return cp-state dict if agent_id matches, else None.

    Unlike _match_cp_state (which returns just agent_type), this returns
    the full payload so disambiguation in _scan_cp_state_files can inspect
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


def _lookup_dev_registry_index(agent_id: str, project_dir: str) -> Optional[str]:
    index_path = f"{project_dir}/.claude/dev-registry/agent-index.json"
    data = _read_json(index_path)
    if not data:
        return None
    value = data.get(agent_id)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        t = value.get("agent_type")
        return t if isinstance(t, str) else None
    return None


def resolve_dev_registry_entry(agent_id: str, project_dir: str) -> Optional[dict]:
    """Return a normalized entry dict for agent_id, or None.

    Always returns {"agent_type": str, "dev_session_id": str|None}.
    Handles both legacy flat-string values (wraps as {"agent_type": value,
    "dev_session_id": None}) and M0 object values (normalizes via .get()
    so missing keys never cause KeyError on malformed entries).
    Returns None when agent_id is absent, agent_type is not a str, or
    any I/O error occurs.
    Used by posttool-codex-skill-ledger.py and subagentstop-codex-enforce.py
    to access both agent_type AND dev_session_id from a single index read.
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
    if not matches:
        return None
    # STALE-1: is_running=true alone is not enough -- a dangling entry that
    # was never checked out also has is_running=true forever. Require the
    # match to also be fresh (recently checked in) before trusting it.
    active = [m for m in matches if m.get("is_running") and not _is_stale(m)]
    if not active:
        return None
    picked = _pick_active(active)
    return _FAIL_CLOSED if picked is None else picked


def _resolve_by_id(agent_id: str) -> Optional[str]:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    spec_hit = _scan_cp_state_files(agent_id, project_dir)
    if spec_hit is _FAIL_CLOSED:
        return None  # active collision: deny, do NOT consult agent-index
    if isinstance(spec_hit, str):
        return spec_hit
    return _lookup_dev_registry_index(agent_id, project_dir)


def resolve_agent_type(payload: dict) -> Optional[str]:
    """Public API: PreToolUse stdin payload -> agent_type or None."""
    if not isinstance(payload, dict):
        return None
    direct = payload.get("subagent_type")
    if isinstance(direct, str) and direct:
        return direct
    agent_id = payload.get("agent_id")
    if not agent_id or not isinstance(agent_id, str):
        return None
    return _resolve_by_id(agent_id)
