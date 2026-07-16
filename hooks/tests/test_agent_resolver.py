"""Unit tests for hooks/lib/agent_resolver.py -- STALE-1 (2026-07-15).

Covers the bug: cp-state files that were never checked out (crashed/
abandoned sessions) sit on disk with is_running=true forever. Because
_scan_cp_state_files globs ALL specs and matches purely on agent_id string
equality, a brand-new session whose agent_id happens to coincide with a
stale dangling entry got silently misattributed that entry's role -- even
though it was never dispatched to that spec.

Fix: an is_running=true cp-state match is only trusted as authoritative if
checked_in_at is within _MAX_ACTIVE_AGE_SECONDS of "now". Run with:
  python3 -m pytest hooks/tests/test_agent_resolver.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

# Add repo root to path so we can import hooks.lib.agent_resolver as a module,
# matching hooks/tests/test_bash_safety_context.py's convention.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from hooks.lib.agent_resolver import resolve_agent_type  # noqa: E402


def _iso_ago(hours):
    """ISO-8601 UTC timestamp `hours` before now -- avoids hardcoding a fixed
    historical date so the test's staleness margin stays meaningful regardless
    of when it runs."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_cp_state(project_dir, spec_id, agent_type, *, agent_id,
                     is_running=True, checked_in_at=None, checkpoints=None):
    cp_dir = project_dir / ".claude" / "specs" / spec_id
    cp_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": spec_id,
        "agent_type": agent_type,
        "instance_id": None,
        "generation": 1,
        "agent_id": agent_id,
        "is_running": is_running,
        "checked_in_at": checked_in_at,
        "checked_out_at": None,
        "checkpoints": checkpoints or [],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    path = cp_dir / f"cp-state-{agent_type}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_agent_index(project_dir, mapping):
    idx_dir = project_dir / ".claude" / "dev-registry"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "agent-index.json").write_text(json.dumps(mapping), encoding="utf-8")


def _resolve(project_dir, agent_id, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    return resolve_agent_type({
        "tool_name": "Write",
        "agent_id": agent_id,
        "tool_input": {"file_path": "docs/dev/ticket-x.md"},
    })


# -------------------- STALE-1: the reproduced bug + its fix ---------------------

def test_stale_dangling_entry_does_not_misattribute(tmp_path, monkeypatch):
    """A brand-new session must NOT inherit the role of a long-abandoned
    is_running=true entry it never checked into, just because its agent_id
    happens to coincide with the dangling entry's stored agent_id."""
    _write_cp_state(tmp_path, "old-abandoned-spec", "architect",
                     agent_id="reused-agent-id",
                     checked_in_at=_iso_ago(24 * 5))  # 5 days old, well past the 8h threshold
    role = _resolve(tmp_path, "reused-agent-id", monkeypatch)
    assert role is None, (
        f"STALE-1 regression: stale dangling entry misattributed role {role!r}"
    )


def test_fresh_active_entry_still_resolves_no_false_negative(tmp_path, monkeypatch):
    """A genuinely active, recently-checked-in session must resolve normally --
    the staleness fix must not produce false negatives for real in-progress work."""
    now = _iso_ago(0)
    _write_cp_state(tmp_path, "live-spec", "qa", agent_id="genuinely-active-agent",
                     checked_in_at=now,
                     checkpoints=[{"id": "cp-01", "state": "pending",
                                   "waived_reason": None, "updated_at": now}])
    role = _resolve(tmp_path, "genuinely-active-agent", monkeypatch)
    assert role == "qa", f"false negative: genuinely active session resolved as {role!r}"


def test_stale_entry_falls_through_to_agent_index(tmp_path, monkeypatch):
    """Per AC-3 semantics (unchanged): a non-authoritative cp-state hit (here,
    stale rather than inactive) must still fall through to agent-index.json --
    the fallback path itself is untouched by this fix."""
    _write_cp_state(tmp_path, "old-spec", "architect", agent_id="idx-agent",
                     checked_in_at=_iso_ago(24 * 60))  # 60 days old
    _write_agent_index(tmp_path, {"idx-agent": "ba"})
    role = _resolve(tmp_path, "idx-agent", monkeypatch)
    assert role == "ba", f"expected agent-index fallback 'ba', got {role!r}"


def test_missing_checked_in_at_treated_as_stale(tmp_path, monkeypatch):
    """Fail-safe: a malformed/missing checked_in_at on an is_running=true entry
    must not be trusted indefinitely; treat as stale (excluded)."""
    cp_dir = tmp_path / ".claude" / "specs" / "malformed-spec"
    cp_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": "malformed-spec", "agent_type": "dev", "agent_id": "malformed-agent",
        "is_running": True, "checked_in_at": None, "checked_out_at": None,
        "checkpoints": [], "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    (cp_dir / "cp-state-dev.json").write_text(json.dumps(payload), encoding="utf-8")
    role = _resolve(tmp_path, "malformed-agent", monkeypatch)
    assert role is None, f"missing checked_in_at should fail safe to None, got {role!r}"


def test_far_future_checked_in_at_treated_as_stale(tmp_path, monkeypatch):
    """Codex finding (c): a checked_in_at in the future (clock skew or a
    corrupt/adversarial entry) makes age negative; without a floor,
    age > max_age_seconds is never true and the entry would be trusted as
    fresh forever. Must be treated as stale/untrusted, not eternally fresh."""
    _write_cp_state(tmp_path, "future-spec", "architect", agent_id="future-agent",
                     checked_in_at=_iso_ago(-24))  # 24h in the future
    role = _resolve(tmp_path, "future-agent", monkeypatch)
    assert role is None, f"far-future checked_in_at should be treated as stale, got {role!r}"


def test_small_clock_skew_still_tolerated(tmp_path, monkeypatch):
    """A few minutes of clock skew into the future (ordinary NTP drift, or a
    write landing just after this process's `now` snapshot) must not be
    treated as stale -- only far-future timestamps are suspicious."""
    _write_cp_state(tmp_path, "skew-spec", "qa", agent_id="skew-agent",
                     checked_in_at=_iso_ago(-2 / 60))  # ~2 seconds in the future
    role = _resolve(tmp_path, "skew-agent", monkeypatch)
    assert role == "qa", f"small clock skew should still resolve normally, got {role!r}"


# -------------------- regression: existing behavior must be preserved ---------------------

def test_cross_role_active_collision_still_fails_closed(tmp_path, monkeypatch):
    """F14 M8 regression: two FRESH is_running=true entries for the SAME
    agent_id but DIFFERENT roles must still fail closed (None), never guess."""
    now = _iso_ago(0)
    _write_cp_state(tmp_path, "collide-spec-1", "qa", agent_id="collided-id", checked_in_at=now)
    _write_cp_state(tmp_path, "collide-spec-2", "architect", agent_id="collided-id", checked_in_at=now)
    role = _resolve(tmp_path, "collided-id", monkeypatch)
    assert role is None, f"F14 M8 regression: cross-role collision resolved to {role!r}"


def test_same_role_active_collision_still_resolves(tmp_path, monkeypatch):
    """F14 M9 regression: two FRESH is_running=true entries for the SAME
    agent_id AND SAME role (e.g. two numbered instance slots) still resolve
    deterministically to that shared role."""
    now = _iso_ago(0)
    _write_cp_state(tmp_path, "parallel-spec-1", "qa", agent_id="same-role-id", checked_in_at=now)
    _write_cp_state(tmp_path, "parallel-spec-2", "qa", agent_id="same-role-id", checked_in_at=now)
    role = _resolve(tmp_path, "same-role-id", monkeypatch)
    assert role == "qa", f"F14 M9 regression: same-role collision resolved to {role!r}"


def test_subagent_type_direct_short_circuit_unaffected(tmp_path, monkeypatch):
    """Step 1 (payload.subagent_type direct hit) must remain untouched by
    the cp-state staleness fix -- it never reaches _scan_cp_state_files."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    role = resolve_agent_type({"subagent_type": "qa", "agent_id": "whatever"})
    assert role == "qa"


def test_no_cp_state_files_falls_through_to_none(tmp_path, monkeypatch):
    role = _resolve(tmp_path, "nobody-agent", monkeypatch)
    assert role is None
