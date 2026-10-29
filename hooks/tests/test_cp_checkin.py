"""Tests for pretool-cp-checkin.py and scripts/spec-check.py covering ACs 1-10
of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field).

Each test runs the hook or spec-check.py as a subprocess with synthesized
stdin JSON and CLAUDE_PROJECT_DIR pointed at a tmp_path directory.
Tests do NOT mutate live specs files. Uses idiomatic pytest fixtures.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


HOOK = Path(__file__).parent.parent / "pretool-cp-checkin.py"
SPEC_CHECK = Path(__file__).parent.parent.parent / "scripts" / "spec-check.py"


# -------------------- helpers ---------------------

def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_cp_state(project_dir: Path, spec_id: str, agent: str,
                   payload: dict) -> Path:
    cp_dir = project_dir / ".claude" / "specs" / spec_id
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / f"cp-state-{agent}.json"
    cp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return cp_path


def _run_hook(project_dir: Path, stdin_obj, raw_stdin=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    inp = raw_stdin if raw_stdin is not None else json.dumps(stdin_obj)
    return subprocess.run(["python3", str(HOOK)], input=inp, text=True,
                          capture_output=True, env=env, timeout=15)


def _run_spec_check(project_dir: Path, args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(["python3", str(SPEC_CHECK)] + list(args),
                          text=True, capture_output=True, env=env, timeout=15)


def _read_cp(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_payload(spec_id, agent, *, generation=None, checkpoints=None,
                      agent_id=None, is_running=False):
    p = {
        "spec_id": spec_id,
        "agent_type": agent,
        "instance_id": None,
        "agent_id": agent_id,
        "is_running": is_running,
        "checked_in_at": None,
        "checked_out_at": None,
        "checkpoints": checkpoints or [],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    if generation is not None:
        p["generation"] = generation
    return p


def _cp(cp_id, *, state="pending", waived_reason=None):
    return {
        "id": cp_id, "action": f"do-{cp_id}", "state": state,
        "waived_reason": waived_reason, "updated_at": _now_iso(),
    }


def _assert_no_traceback(rc, label=""):
    assert rc.returncode == 0, (
        f"{label} expected exit 0, got rc={rc.returncode} stderr={rc.stderr!r}"
    )
    assert "Traceback" not in (rc.stderr or ""), (
        f"{label} unexpected traceback in stderr={rc.stderr!r}"
    )


# -------------------- AC1: view-file Read MUST be no-op ---------------------

def test_ac1_view_read_does_not_mutate(tmp_path):
    spec_id, agent = "spec-test-ac1", "ba"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, checkpoints=[_cp("cp-01", state="done")]))
    view = tmp_path / "docs" / "dev" / "specs" / spec_id / "views" / f"{agent}.md"
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text("# view", encoding="utf-8")

    before = cp_path.read_bytes()
    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(view)},
                               "agent_id": "explore-aaaa"})
    assert rc.returncode == 0, f"AC1 expected exit 0, got rc={rc.returncode}"
    assert before == cp_path.read_bytes(), (
        "AC1: cp-state mutated by view-file Read; expected byte-identical"
    )


# -------------------- AC2: cp-state direct Read registers + preserves ---------------------

def test_ac2_direct_read_registers_and_preserves(tmp_path):
    spec_id, agent = "spec-test-ac2", "ba"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1,
        checkpoints=[_cp("cp-01", state="done"),
                     _cp("cp-02", state="waived-with-reason",
                         waived_reason="qa-asked-for-this")]))

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "real-abcd1234"})
    _assert_no_traceback(rc, "AC2")
    after = _read_cp(cp_path)
    assert after.get("is_running") is True, f"AC2: is_running not set: {after}"
    assert after.get("agent_id") == "real-abcd1234", (
        f"AC2: agent_id mismatch: {after.get('agent_id')!r}"
    )
    cps = after["checkpoints"]
    assert cps[0].get("state") == "done", f"AC2: cp-01 not done: {cps[0]}"
    assert (cps[1].get("state") == "waived-with-reason"
            and cps[1].get("waived_reason") == "qa-asked-for-this"), (
        f"AC2: cp-02 state/reason mismatch: {cps[1]}"
    )


# -------------------- AC3: dev-sentinel updates index ---------------------

def test_ac3_dev_sentinel_updates_index(tmp_path):
    sid, agent = "dev-test-sid", "ba"
    sentinel = tmp_path / ".claude" / "dev-registry" / sid / f"{agent}.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}", encoding="utf-8")

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(sentinel)},
                               "agent_id": "abc-real"})
    _assert_no_traceback(rc, "AC3")
    idx = tmp_path / ".claude" / "dev-registry" / "agent-index.json"
    assert idx.exists(), "AC3: agent-index.json missing"
    m = json.loads(idx.read_text(encoding="utf-8"))
    entry = m.get("abc-real")
    assert isinstance(entry, dict), f"AC3: no entry for abc-real in index: {m}"
    assert entry.get("agent_type") == agent, (
        f"AC3: agent_type mismatch: {entry.get('agent_type')!r}"
    )
    assert entry.get("dev_session_id") == sid, (
        f"AC3: dev_session_id mismatch: {entry.get('dev_session_id')!r}"
    )


# -------------------- AC4: SECOND ACTION protocol still works ---------------------

def test_ac4_second_action_still_registers(tmp_path):
    for agent in ("ba", "dev", "qa"):
        cp_path = _make_cp_state(tmp_path, "spec-test-ac4", agent, _baseline_payload(
            "spec-test-ac4", agent, generation=1, checkpoints=[_cp("cp-01")]))
        rc = _run_hook(tmp_path, {"tool_name": "Read",
                                   "tool_input": {"file_path": str(cp_path)},
                                   "agent_id": f"id-{agent}"})
        assert rc.returncode == 0, (
            f"AC4.{agent}: expected exit 0, got rc={rc.returncode}"
        )
        after = _read_cp(cp_path)
        assert after.get("is_running") is True and after.get("agent_id") == f"id-{agent}", (
            f"AC4.{agent}: not registered: {after}"
        )


# -------------------- AC5: missing generation -> 1, no implicit reset ---------------------

def test_ac5_missing_generation_no_reset(tmp_path):
    spec_id, agent = "spec-test-ac5", "ba"
    payload = _baseline_payload(spec_id, agent,
                                checkpoints=[_cp("cp-01", state="done")])
    cp_path = _make_cp_state(tmp_path, spec_id, agent, payload)

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "id-ac5"})
    _assert_no_traceback(rc, "AC5")
    after = _read_cp(cp_path)
    assert after["checkpoints"][0].get("state") == "done", (
        f"AC5: cp-01 state changed: {after}"
    )
    # OBJ-2: hook MUST NOT silently back-fill the generation field on rewrite.
    assert "generation" not in after, (
        f"AC5: generation field silently back-filled: {after!r}"
    )


# -------------------- AC6: takeover inherits done states ---------------------

def test_ac6_takeover_inherits_done(tmp_path):
    spec_id, agent = "spec-test-ac6", "ba"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1, agent_id="prev-zzz", is_running=False,
        checkpoints=[_cp("cp-01", state="done"),
                     _cp("cp-02", state="done"),
                     _cp("cp-03", state="done")]))

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "next-bbb"})
    _assert_no_traceback(rc, "AC6")
    after = _read_cp(cp_path)
    assert after.get("is_running") is True, f"AC6: is_running not set: {after}"
    assert after.get("agent_id") == "next-bbb", (
        f"AC6: agent_id mismatch: {after.get('agent_id')!r}"
    )
    states = [cp.get("state") for cp in after.get("checkpoints", [])]
    assert states == ["done", "done", "done"], (
        f"AC6: done states not preserved: {states!r}"
    )


# -------------------- AC7: --bump-generation resets ---------------------

def test_ac7_bump_generation(tmp_path):
    spec_id, agent = "spec-test-ac7", "ba"
    payload = _baseline_payload(
        spec_id, agent, generation=1, agent_id="prev-zzz",
        checkpoints=[_cp("cp-01", state="done"),
                     _cp("cp-02", state="waived-with-reason",
                         waived_reason="qa-blocked"),
                     _cp("cp-03", state="pending")])
    payload["updated_at"] = "2026-04-27T10:00:00Z"  # cp-state-level marker
    cp_path = _make_cp_state(tmp_path, spec_id, agent, payload)

    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id,
                                     "--agent", agent, "--agent-id", "fresh-aaa",
                                     "--bump-generation"])
    _assert_no_traceback(rc, "AC7")
    after = _read_cp(cp_path)
    assert after.get("generation") == 2, (
        f"AC7: expected generation=2, got {after.get('generation')!r}"
    )
    states = [cp.get("state") for cp in after.get("checkpoints", [])]
    assert states == ["pending"] * 3, f"AC7: states not reset to pending: {states}"
    reasons = [cp.get("waived_reason") for cp in after.get("checkpoints", [])]
    assert reasons == [None, None, None], (
        f"AC7: waived_reasons not cleared: {reasons}"
    )
    assert after.get("is_running") is True, "AC7: is_running not set"
    # OBJ-3: cp-state-level updated marker refreshed on bump.
    assert after.get("updated_at") not in (None, "", "2026-04-27T10:00:00Z"), (
        f"AC7: updated_at not refreshed: {after.get('updated_at')!r}"
    )


# -------------------- AC8: waived survives normal takeover ---------------------

def test_ac8_waived_survives_takeover(tmp_path):
    spec_id, agent = "spec-test-ac8", "ba"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1, is_running=False, agent_id="old",
        checkpoints=[_cp("cp-01", state="waived-with-reason",
                         waived_reason="qa-asked-for-this")]))

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "new-takeover"})
    _assert_no_traceback(rc, "AC8")
    cp = _read_cp(cp_path)["checkpoints"][0]
    assert cp.get("state") == "waived-with-reason", (
        f"AC8: state changed: {cp}"
    )
    assert cp.get("waived_reason") == "qa-asked-for-this", (
        f"AC8: waived_reason changed: {cp}"
    )


# -------------------- AC10a-c: negative tests ---------------------

def test_ac10a_malformed_stdin(tmp_path):
    rc = _run_hook(tmp_path, None, raw_stdin="not-json{")
    _assert_no_traceback(rc, "AC10a")


def test_ac10b_missing_tool_name(tmp_path):
    rc = _run_hook(tmp_path, {"tool_input": {"file_path": str(tmp_path / "anything")},
                               "agent_id": "x"})
    _assert_no_traceback(rc, "AC10b")


def test_ac10c_missing_agent_id_for_sentinel(tmp_path):
    sentinel = tmp_path / ".claude" / "dev-registry" / "dev-no-id" / "ba.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}", encoding="utf-8")

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(sentinel)}})
    _assert_no_traceback(rc, "AC10c")
    idx = tmp_path / ".claude" / "dev-registry" / "agent-index.json"
    assert not idx.exists(), (
        "AC10c: agent-index.json should not exist when agent_id is missing"
    )


# -------------------- AC10d: concurrent --bump-generation ---------------------

def _bump_one(tmp_dir, spec_id, agent, tag, results):
    results[tag] = _run_spec_check(tmp_dir, [
        "check-in", "--spec-id", spec_id, "--agent", agent,
        "--agent-id", f"id-{tag}", "--bump-generation"])


def test_ac10d_concurrent_bump_generation(tmp_path):
    spec_id, agent = "spec-test-ac10d", "ba"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1,
        checkpoints=[_cp("cp-01", state="done")]))
    results = {}
    threads = [threading.Thread(target=_bump_one,
                                args=(tmp_path, spec_id, agent, t, results))
               for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert all(results[t].returncode == 0 for t in ("a", "b")), (
        f"AC10d: both processes must exit 0; "
        f"a.stderr={results['a'].stderr!r} b.stderr={results['b'].stderr!r}"
    )
    final = _read_cp(cp_path)
    assert final.get("generation") == 3, (
        f"AC10d: final generation={final.get('generation')!r} (expected 3); "
        f"OBJ-2 invariant: read-modify-write must be under exclusive lock"
    )


# -------------------- STALE-1: idempotent checked_in_at (Codex finding a) ---------------------

def test_stale1_repeat_read_same_owner_does_not_refresh_checked_in_at(tmp_path):
    """A repeat Read by the SAME already-registered owner of an already-running
    slot must NOT restamp checked_in_at -- otherwise a bystander session that
    incidentally re-reads a cp-state path it auto-registered into could keep
    that registration perpetually "fresh", defeating agent_resolver.py's
    staleness bound (hooks/lib/agent_resolver.py _MAX_ACTIVE_AGE_SECONDS)."""
    spec_id, agent = "spec-test-stale1", "architect"
    old_ts = "2026-01-01T00:00:00Z"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1, agent_id="bystander-agent", is_running=True,
        checkpoints=[_cp("cp-01", state="pending")]))
    payload = _read_cp(cp_path)
    payload["checked_in_at"] = old_ts
    cp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "bystander-agent"})
    _assert_no_traceback(rc, "STALE-1")
    after = _read_cp(cp_path)
    assert after.get("checked_in_at") == old_ts, (
        f"STALE-1 regression: repeat same-owner Read refreshed checked_in_at: {after.get('checked_in_at')!r}"
    )
    assert after.get("is_running") is True


def test_stale1_new_owner_takeover_still_refreshes_checked_in_at(tmp_path):
    """A genuine takeover (different agent_id claiming an is_running=false
    slot, or an idle slot's first registration) must still refresh
    checked_in_at -- only the SAME-owner repeat-read path is idempotent."""
    spec_id, agent = "spec-test-stale1b", "architect"
    old_ts = "2026-01-01T00:00:00Z"
    cp_path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1, agent_id="old-owner", is_running=False,
        checkpoints=[_cp("cp-01", state="pending")]))
    payload = _read_cp(cp_path)
    payload["checked_in_at"] = old_ts
    cp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rc = _run_hook(tmp_path, {"tool_name": "Read",
                               "tool_input": {"file_path": str(cp_path)},
                               "agent_id": "new-owner"})
    _assert_no_traceback(rc, "STALE-1b")
    after = _read_cp(cp_path)
    assert after.get("checked_in_at") != old_ts, (
        "STALE-1b regression: genuine new-owner takeover did not refresh checked_in_at"
    )
    assert after.get("agent_id") == "new-owner"
    assert after.get("is_running") is True


# -------------------- the roster decides who registers (P1b row 18) ----------

def _roster_roles():
    import importlib.util
    spec = importlib.util.spec_from_file_location("roster_under_test", HOOK.parent / "lib" / "roster.py")
    roster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(roster)
    return roster.roles()


def test_every_roster_role_registers_and_nothing_else(tmp_path):
    """Both triggers accept exactly the roster (agents/*.md with front
    matter), graphify among it (spec-20260527-061433 AC5); neither keeps a
    list of its own. A sentinel or cp-state name that is no agent registers
    nobody."""
    roles = _roster_roles()
    assert "graphify" in roles and "changelog-analyst" in roles
    registry = tmp_path / ".claude" / "dev-registry" / "dev-roster-sid"
    for index, name in enumerate(sorted(roles) + ["wizard", "README"]):
        rc = _run_hook(tmp_path, {"tool_name": "Read",
                                  "tool_input": {"file_path": str(registry / f"{name}.json")},
                                  "agent_id": f"agent-{index}"})
        _assert_no_traceback(rc, name)
    index = json.loads((tmp_path / ".claude" / "dev-registry" / "agent-index.json").read_text())
    assert {entry["agent_type"] for entry in index.values()} == roles


def test_spec_check_accepts_exactly_the_roster(tmp_path):
    """spec-check.py's agents are the roster: graphify and the analysts check
    in; a name no agent file declares is refused naming the roster."""
    for agent in ("graphify", "pull-analyst", "test-writer"):
        rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", "spec-roster", "--agent", agent,
                                        "--agent-id", f"id-{agent}"])
        assert rc.returncode == 0, (agent, rc.stderr)
    refused = _run_spec_check(tmp_path, ["check-in", "--spec-id", "spec-roster", "--agent", "wizard",
                                         "--agent-id", "id-wizard"])
    assert refused.returncode == 1
    assert "unknown agent 'wizard'" in refused.stderr
    assert ", ".join(sorted(_roster_roles())) in refused.stderr


# -------------------- check-in over a missing, corrupt or empty primary ---------------------
# spec-check.py's documented contract (its docstring: missing files default-initialize,
# corrupt files are overwritten fail-forward; agents/spec.md: check-in creates the cp-state
# file). A first check-in must never be refused for want of a primary slot.

@pytest.mark.parametrize("mode", ["missing", "corrupt", "empty"])
def test_checkin_binds_primary_when_missing_corrupt_or_empty(tmp_path, mode):
    spec_id, agent = "spec-lb", "dev"
    primary = tmp_path / ".claude" / "specs" / spec_id / f"cp-state-{agent}.json"
    primary.parent.mkdir(parents=True)
    if mode == "corrupt":
        primary.write_text("{", encoding="utf-8")
    elif mode == "empty":
        primary.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")

    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id,
                                    "--agent", agent, "--agent-id", "owner"])

    _assert_no_traceback(rc, f"check-in over {mode} primary")
    assert (f"checked in: spec={spec_id} agent={agent} slot=primary agent-id=owner"
            in rc.stdout)
    assert f"cp-state-path: {primary}" in rc.stdout
    if mode == "corrupt":
        assert "corrupt cp-state" in rc.stderr and "reinitializing" in rc.stderr
    payload = _read_cp(primary)
    assert payload["agent_id"] == "owner"
    assert payload["is_running"] is True
    assert payload["checkpoints"] == []
    if mode != "empty":
        assert payload["spec_id"] == spec_id
        assert payload["agent_type"] == agent
        assert payload["generation"] == 1
        assert payload["terminal_artifact"] == {
            "path": None, "exists": False, "validated_at": None}
    assert not list(primary.parent.glob(f"cp-state-{agent}-[0-9]*.json"))


def test_first_checkin_creates_primary_cp_state(tmp_path):
    spec_id = "continuation-gitclean-20260809"
    primary = tmp_path / ".claude" / "specs" / spec_id / "cp-state-dev.json"

    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id, "--agent", "dev",
                                    "--agent-id", "spec-provider-1"])

    _assert_no_traceback(rc, "first check-in")
    payload = _read_cp(primary)
    assert payload["spec_id"] == spec_id
    assert payload["agent_type"] == "dev"
    assert payload["instance_id"] is None
    assert payload["generation"] == 1
    assert payload["agent_id"] == "spec-provider-1"
    assert payload["is_running"] is True
    assert payload["checkpoints"] == []


# -------------------- 48 concurrent check-ins allocate distinct numbered slots ---------------------

@pytest.mark.parametrize("run", range(2))
def test_48_way_checkin_allocates_distinct_numbered_slots(tmp_path, run):
    spec_id, agent = "spec-lb", "dev"
    root = tmp_path / f"run-{run}"
    primary = _make_cp_state(root, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=4, agent_id="primary-owner", is_running=True,
        checkpoints=[_cp("cp-01", state="done"),
                     _cp("cp-02", state="waived-with-reason", waived_reason="old")]))
    before = primary.read_bytes()
    owners = [f"cli-owner-{index}" for index in range(48)]

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(
            lambda owner: _run_spec_check(root, [
                "check-in", "--spec-id", spec_id, "--agent", agent,
                "--agent-id", owner]),
            owners))

    assert all(result.returncode == 0 for result in results), [
        result.stderr for result in results if result.returncode
    ]
    numbered = sorted(primary.parent.glob(f"cp-state-{agent}-[0-9]*.json"))
    assert len(numbered) == 48
    payloads = [_read_cp(path) for path in numbered]
    assert {payload["agent_id"] for payload in payloads} == set(owners)
    assert sorted(payload["instance_id"] for payload in payloads) == list(range(2, 50))
    for path, payload in zip(numbered, payloads):
        assert path.name == f"cp-state-{agent}-{payload['instance_id']}.json"
        assert payload["is_running"] is True
        assert payload["generation"] == 1
        assert payload["checkpoints"] == []
    assert primary.read_bytes() == before


# -------------------- spec-check.py is the one writer (P1b row 8) ---------------------

def test_checkpoints_sets_the_checklist_of_the_callers_slot(tmp_path):
    spec_id, agent = "spec-test-cps", "ba"
    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id, "--agent", agent,
                                    "--agent-id", "spec-lead-ba"])
    _assert_no_traceback(rc, "check-in")
    path = tmp_path / ".claude" / "specs" / spec_id / f"cp-state-{agent}.json"
    rc = _run_spec_check(tmp_path, ["checkpoints", "--spec-id", spec_id, "--agent", agent,
                                    "--agent-id", "spec-lead-ba", "--action", "Write the ticket",
                                    "--action", "Write the context"])
    _assert_no_traceback(rc, "checkpoints")
    cps = _read_cp(path)["checkpoints"]
    assert [(c["id"], c["action"], c["state"]) for c in cps] == [
        ("cp-01", "Write the ticket", "pending"), ("cp-02", "Write the context", "pending")]
    before = path.read_bytes()
    rc = _run_spec_check(tmp_path, ["checkpoints", "--spec-id", spec_id, "--agent", agent,
                                    "--agent-id", "someone-else", "--action", "x"])
    assert rc.returncode == 1 and "owned by agent_id 'someone-else'" in rc.stderr
    assert path.read_bytes() == before


def test_register_of_a_second_agent_clones_the_primary_checklist(tmp_path):
    spec_id, agent = "spec-test-clone", "qa"
    primary = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(
        spec_id, agent, generation=1, agent_id="spec-lead-qa", is_running=True,
        checkpoints=[_cp("cp-01"), _cp("cp-02", state="done")]))
    before = primary.read_bytes()
    rc = _run_hook(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(primary)},
                              "agent_id": "real-qa-1"})
    _assert_no_traceback(rc, "register")
    clone = _read_cp(primary.with_name(f"cp-state-{agent}-2.json"))
    assert clone["agent_id"] == "real-qa-1" and clone["is_running"] is True and clone["instance_id"] == 2
    assert [c["state"] for c in clone["checkpoints"]] == ["pending", "done"]
    assert primary.read_bytes() == before


def test_a_read_without_an_agent_id_registers_nobody(tmp_path):
    spec_id, agent = "spec-test-main-read", "dev"
    path = _make_cp_state(tmp_path, spec_id, agent, _baseline_payload(spec_id, agent, generation=1))
    before = path.read_bytes()
    rc = _run_hook(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(path)}})
    _assert_no_traceback(rc, "main read")
    assert path.read_bytes() == before


def test_cp_enforce_and_role_resolution_take_one_running_rule(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
    from agent_resolver import cp_state_running

    enforce = Path(__file__).parent.parent / "subagentstop-cp-enforce.py"
    spec_id, agent = "spec-test-running", "dev"
    fresh = _baseline_payload(spec_id, agent, generation=1, agent_id="a-1", is_running=True,
                              checkpoints=[_cp("cp-01")])
    fresh["checked_in_at"] = _now_iso()
    stale = dict(fresh, checked_in_at="2020-01-01T00:00:00Z")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "CP_ENFORCE_MODE": "block"}
    for payload, running, code in ((fresh, True, 2), (stale, False, 0)):
        _make_cp_state(tmp_path, spec_id, agent, payload)
        assert cp_state_running(payload) is running
        rc = subprocess.run(["python3", str(enforce)], input="{}", text=True, capture_output=True,
                            env=env, timeout=15)
        assert rc.returncode == code, rc.stderr
