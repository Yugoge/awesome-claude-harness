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
from pathlib import Path


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


# -------------------- graphify registration (spec-20260527-061433) ----------

def test_graphify_in_cp_agents():
    """Verify 'graphify' is registered in CP_AGENTS (pretool-cp-checkin.py).

    AC5 from spec-20260527-061433: graphify must appear in CP_AGENTS, ALLOWED_AGENTS,
    and agent_types list together (arch-2 precedent: test-writer pattern).
    """
    hook_text = HOOK.read_text(encoding="utf-8")
    assert ('"graphify"' in hook_text or "'graphify'" in hook_text), (
        "CP_AGENTS in pretool-cp-checkin.py must include 'graphify' (spec-20260527-061433 AC5)"
    )


def test_graphify_in_allowed_agents():
    """Verify 'graphify' is registered in ALLOWED_AGENTS (scripts/spec-check.py).

    Symmetry with CP_AGENTS per arch-2 precedent.
    """
    spec_check_text = SPEC_CHECK.read_text(encoding="utf-8")
    assert ('"graphify"' in spec_check_text or "'graphify'" in spec_check_text), (
        "ALLOWED_AGENTS in scripts/spec-check.py must include 'graphify' (spec-20260527-061433 AC5)"
    )


# ==================== LANE-B r02 provider evidence (P-G2-3) ====================
# The four test ids below are named in acceptance-criteria-20260829-132955-r02
# AC-R02-05 check.p_g2_3_named_test_ids and are the evidence r07's gate G2 reads.

_LIB = Path(__file__).parent.parent / "lib"


def _import_checkpoint_resources():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_r02_checkpoint_resources", _LIB / "checkpoint_resources.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _eight_waived(actor="qa-r06-bavalidation-3449939", when="2026-08-30T12:20:57Z"):
    return [
        {"id": f"cp-0{i}", "action": f"action {i}", "state": "waived-with-reason",
         "waived_reason": f"waived by {actor} at {when}", "updated_at": when}
        for i in range(1, 9)
    ]


def _eight_master(state="pending"):
    return [
        {"id": f"cp-0{i}", "action": f"action {i}", "state": state,
         "waived_reason": None, "updated_at": "2026-08-01T00:00:00Z"}
        for i in range(1, 9)
    ]


def test_clone_preserves_ids_pending_reset(tmp_path):
    """P-G2-3 id=clone_preserves_ids_pending_reset.

    A second actor checking in against a RUNNING primary must receive the
    NUMBERED slot cp-state-qa-2.json carrying the master's checkpoint ids in
    order, every one reset to pending, with waiver and audit data cleared and
    timestamps refreshed. The prior check accepted any nonempty all-pending
    slot and did not force numbered allocation.
    """
    spec_id = "spec-clone"
    master = _eight_master(state="done")
    master[0]["state"] = "waived-with-reason"
    master[0]["waived_reason"] = "duress"
    master[0]["audit_history"] = [{"prior_state": "waived-with-reason"}]
    payload = _baseline_payload(spec_id, "qa", generation=3, checkpoints=master,
                                agent_id="actor-primary", is_running=True)
    primary = _make_cp_state(tmp_path, spec_id, "qa", payload)

    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id,
                                    "--agent", "qa", "--agent-id", "actor-two"])
    _assert_no_traceback(rc, "numbered allocation")
    assert rc.returncode == 0, rc.stderr

    numbered = primary.parent / "cp-state-qa-2.json"
    assert numbered.exists(), f"expected cp-state-qa-2.json, got {sorted(p.name for p in primary.parent.iterdir())}"
    assert f"cp-state-path: {numbered}" in rc.stdout

    clone = _read_cp(numbered)
    assert [c["id"] for c in clone["checkpoints"]] == [c["id"] for c in master]
    assert all(c["state"] == "pending" for c in clone["checkpoints"])
    assert all(c["waived_reason"] is None for c in clone["checkpoints"])
    assert all(not c.get("audit_history") for c in clone["checkpoints"])
    assert all(c["updated_at"] != "2026-08-01T00:00:00Z" for c in clone["checkpoints"])
    assert clone["updated_at"] and clone["instance_id"] == 2
    assert clone["agent_id"] == "actor-two" and clone["is_running"] is True
    # The master is untouched by the allocation.
    assert _read_cp(primary)["checkpoints"] == master


def test_empty_or_absent_master_named_nonzero_exit(tmp_path):
    """P-G2-3 id=empty_or_absent_master_named_nonzero_exit.

    An empty or absent primary template must fail LOUDLY with a NAMED error
    code and a non-zero exit, never by silently minting an unusable slot.
    """
    spec_id = "spec-empty"
    empty = _baseline_payload(spec_id, "qa", generation=1, checkpoints=[],
                              agent_id="actor-primary", is_running=True)
    _make_cp_state(tmp_path, spec_id, "qa", empty)
    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id,
                                    "--agent", "qa", "--agent-id", "actor-two"])
    assert "Traceback" not in rc.stderr, rc.stderr
    assert rc.returncode == 1, "a loud NAMED failure, not a crash and not a pass"
    assert json.loads(rc.stdout.strip())["error_code"] == "checkpoint_template_empty"

    rc2 = _run_spec_check(tmp_path, ["check-in", "--spec-id", "spec-absent",
                                     "--agent", "qa", "--agent-id", "actor-two"])
    assert "Traceback" not in rc2.stderr, rc2.stderr
    assert rc2.returncode == 1
    assert json.loads(rc2.stdout.strip())["error_code"] == "checkpoint_template_missing"

    cp_dir = tmp_path / ".claude" / "specs" / "spec-empty"
    assert not (cp_dir / "cp-state-qa-2.json").exists()
    assert not (cp_dir / ".cp-checkin.lock").exists(), (
        "an invalid template must not even create the directory lock artifact"
    )


def test_shared_cp_checkin_lock_covers_scan_pick_write(tmp_path):
    """P-G2-3 id=shared_cp_checkin_lock_covers_scan_pick_write.

    Proof BY EXECUTION that the Read-hook entrypoint reaches the SAME
    checkpoint_resources.directory_transaction the CLI reaches, rather than a
    private scan/clone that merely opens a lock file of the same name.

    Two observables, both FALSE of the unmodified baseline:

    (1) MUTUAL EXCLUSION THROUGH THE SHARED OBJECT -- while a holder occupies
        checkpoint_resources.directory_transaction, the hook cannot complete
        its registration.
    (2) FAIL-CLOSED ON AN ABSENT SHARED MODULE -- with lib.checkpoint_resources
        unavailable the hook performs NO registration. The baseline hook has no
        dependency on that module and registers regardless, so this observable
        cannot be satisfied by unmodified code.
    """
    import shutil
    import threading as _threading

    spec_id = "spec-sharedlock"
    payload = _baseline_payload(spec_id, "qa", generation=1,
                                checkpoints=_eight_master(), is_running=False)
    primary = _make_cp_state(tmp_path, spec_id, "qa", payload)
    resources = _import_checkpoint_resources()

    entered = _threading.Event()
    release = _threading.Event()

    def _hold():
        with resources.directory_transaction(primary):
            entered.set()
            release.wait(timeout=30)

    holder = _threading.Thread(target=_hold, daemon=True)
    holder.start()
    assert entered.wait(timeout=10)

    stdin = json.dumps({"tool_name": "Read", "agent_id": "hook-actor",
                        "tool_input": {"file_path": str(primary)}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    proc = subprocess.Popen(["python3", str(HOOK)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    proc.stdin.write(stdin)
    proc.stdin.close()
    blocked = False
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        blocked = True
    assert blocked, "the hook completed while the shared transaction was held"
    assert _read_cp(primary)["is_running"] is False

    release.set()
    holder.join(timeout=10)
    assert proc.wait(timeout=15) == 0
    assert _read_cp(primary)["is_running"] is True, "registration must land once released"

    # (2) fail-closed control: same hook bytes, shared module unavailable.
    sandbox = tmp_path / "no-shared-module"
    (sandbox / "lib").mkdir(parents=True)
    (sandbox / "lib" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(HOOK, sandbox / HOOK.name)
    project2 = tmp_path / "project2"
    payload2 = _baseline_payload(spec_id, "qa", generation=1,
                                 checkpoints=_eight_master(), is_running=False)
    primary2 = _make_cp_state(project2, spec_id, "qa", payload2)
    before = primary2.read_bytes()
    rc = subprocess.run(
        ["python3", str(sandbox / HOOK.name)],
        input=json.dumps({"tool_name": "Read", "agent_id": "hook-actor",
                          "tool_input": {"file_path": str(primary2)}}),
        text=True, capture_output=True, timeout=15,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project2)},
    )
    assert rc.returncode == 0, "the hook stays fail-open at the process level"
    assert primary2.read_bytes() == before, (
        "with the shared transaction unavailable the registration must be "
        "ABANDONED, never performed unserialized"
    )


def test_racy_mode_slot_not_reassigned_after_checkin(tmp_path):
    """P-G2-3 id=racy_mode_slot_not_reassigned_after_checkin (AC-R02-11).

    DETERMINISTIC INTERLEAVING, not a sequence. A and B are driven
    concurrently and each parks on a barrier INSIDE the slot census -- after
    scanning, before publishing. If the census ran outside the shared
    directory lock the two would meet at the barrier; because it runs inside,
    the barrier must TIME OUT, and the recorded acquire/release ordering must
    show no overlap. A third actor C then arrives after A and B are allocated
    and before either checks out.
    """
    import threading as _threading

    spec_id = "spec-race"
    payload = _baseline_payload(spec_id, "qa", generation=1,
                                checkpoints=_eight_master(),
                                agent_id="actor-primary", is_running=True)
    primary = _make_cp_state(tmp_path, spec_id, "qa", payload)
    resources = _import_checkpoint_resources()

    events = []
    events_lock = _threading.Lock()
    real_transaction = resources.directory_transaction
    real_census = resources._next_available_slot
    barrier = _threading.Barrier(2)
    local = _threading.local()

    import contextlib

    @contextlib.contextmanager
    def _observed(path):
        tag = getattr(local, "tag", "?")
        with real_transaction(path):
            with events_lock:
                events.append(("acquire", tag))
            try:
                yield
            finally:
                with events_lock:
                    events.append(("release", tag))

    met_at_barrier = []

    def _census(path):
        try:
            barrier.wait(timeout=2)
            met_at_barrier.append(getattr(local, "tag", "?"))
        except _threading.BrokenBarrierError:
            pass
        return real_census(path)

    resources.directory_transaction = _observed
    resources._next_available_slot = _census
    try:
        results = {}

        def _claim(tag):
            local.tag = tag
            results[tag] = resources.claim_slot(primary, agent_id=f"actor-{tag}")

        threads = [_threading.Thread(target=_claim, args=(t,)) for t in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()
    finally:
        resources.directory_transaction = real_transaction
        resources._next_available_slot = real_census

    assert met_at_barrier == [], (
        "A and B met inside the census: scan-pick-write is NOT serialized"
    )
    # Lock-acquisition ordering, observed rather than inferred: strict
    # acquire/release alternation means the second could not enter until the
    # first released.
    assert [kind for kind, _ in events] == ["acquire", "release", "acquire", "release"], events
    assert events[0][1] == events[1][1] and events[2][1] == events[3][1]
    assert {events[0][1], events[2][1]} == {"A", "B"}

    assert results["A"]["status"] == "pass" and results["B"]["status"] == "pass"
    slot_a, slot_b = results["A"]["instance_id"], results["B"]["instance_id"]
    assert slot_a != slot_b, (slot_a, slot_b)
    bindings = {}
    for tag in ("A", "B"):
        data = _read_cp(Path(results[tag]["path"]))
        bindings[tag] = (data["agent_id"], data["instance_id"])
        assert data["agent_id"] == f"actor-{tag}"

    result_c = resources.claim_slot(primary, agent_id="actor-C")
    assert result_c["status"] == "pass"
    assert result_c["instance_id"] not in (slot_a, slot_b)
    reassignments = 0
    for tag in ("A", "B"):
        data = _read_cp(Path(results[tag]["path"]))
        if (data["agent_id"], data["instance_id"]) != bindings[tag]:
            reassignments += 1
    assert reassignments == 0, "a slot was reassigned after check-in"

    refused = 0
    for tag in ("A", "B"):
        rc = _run_spec_check(tmp_path, [
            "check-out", "--spec-id", spec_id, "--agent", "qa",
            "--instance-id", str(results[tag]["instance_id"]),
            "--agent-id", f"actor-{tag}",
        ])
        if rc.returncode != 0:
            refused += 1
    assert refused == 0, "a holder was refused checkout after check-in"


def test_bump_generation_cannot_run_beside_a_plain_check_in(tmp_path):
    """--bump-generation and plain check-in both write the PRIMARY file, so
    they must exclude each other through the SAME transaction.

    Serialising two writers of one file on two different lock files does not
    exclude them; this measures the exclusion by execution.
    """
    import threading as _threading

    spec_id = "spec-bumplock"
    payload = _baseline_payload(spec_id, "qa", generation=1,
                                checkpoints=_eight_waived(), is_running=False)
    payload["checked_out_at"] = None
    primary = _make_cp_state(tmp_path, spec_id, "qa", payload)
    resources = _import_checkpoint_resources()

    entered, release = _threading.Event(), _threading.Event()

    def _hold():
        with resources.directory_transaction(primary):
            entered.set()
            release.wait(timeout=30)

    holder = _threading.Thread(target=_hold, daemon=True)
    holder.start()
    assert entered.wait(timeout=10)

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    argv = ["python3", str(SPEC_CHECK), "check-in", "--spec-id", spec_id,
            "--agent", "qa", "--agent-id", "actor-bump", "--bump-generation"]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    blocked = False
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        blocked = True
    assert blocked, "--bump-generation ran while the shared transaction was held"
    assert _read_cp(primary)["generation"] == 1
    assert all(c["state"] == "waived-with-reason" for c in _read_cp(primary)["checkpoints"])

    release.set()
    holder.join(timeout=10)
    assert proc.wait(timeout=15) == 0
    assert _read_cp(primary)["generation"] == 2


def test_bump_generation_reset_preserves_waive_audit(tmp_path):
    """AC-R02-12 fixture proof: the reset path is AUDIT-PRESERVING.

    Re-opening the eight duress-waived checkpoints must not erase the only
    surviving record that they were waived rather than falsely marked done,
    and the appended row must record transitioned_to 'pending', never 'done'.
    """
    spec_id = "spec-reopen"
    waived = _eight_waived()
    payload = _baseline_payload(spec_id, "qa", generation=1, checkpoints=waived,
                                agent_id="qa-r06-bavalidation-3449939")
    payload["checked_out_at"] = None
    primary = _make_cp_state(tmp_path, spec_id, "qa", payload)

    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id, "--agent", "qa",
                                    "--agent-id", "qa-reopen-actor", "--bump-generation"])
    _assert_no_traceback(rc, "audit-preserving reset")
    assert rc.returncode == 0, rc.stderr

    after = _read_cp(primary)
    assert after["generation"] == 2
    assert len(after["checkpoints"]) == 8
    for original, cp in zip(waived, after["checkpoints"]):
        assert cp["state"] == "pending"
        assert cp["waived_reason"] is None
        history = cp.get("audit_history") or []
        assert len(history) == 1, cp
        row = history[0]
        assert row["prior_state"] == "waived-with-reason"
        assert row["prior_waived_reason"] == original["waived_reason"]
        assert row["prior_updated_at"] == original["updated_at"]
        assert row["transitioned_to"] == "pending", "a false 'done' transition was recorded"
        assert row["actor"] == "qa-reopen-actor"
        assert row["transitioned_at"]


def test_bump_generation_does_not_reach_another_roles_cp_state(tmp_path):
    """The audit-preserving reset runs the same cross-role ownership refusal
    mark and waive run, and never mutates another role's slot."""
    spec_id = "spec-scope"
    qa_payload = _baseline_payload(spec_id, "qa", generation=1,
                                   checkpoints=_eight_waived())
    qa_payload["checked_out_at"] = None
    qa_file = _make_cp_state(tmp_path, spec_id, "qa", qa_payload)
    dev_payload = _baseline_payload(spec_id, "dev", generation=1,
                                    checkpoints=[_cp("cp-99", state="waived-with-reason",
                                                     waived_reason="dev duress")])
    dev_payload["checked_out_at"] = None
    _make_cp_state(tmp_path, spec_id, "dev", dev_payload)

    before = qa_file.read_bytes()
    rc = _run_spec_check(tmp_path, ["check-in", "--spec-id", spec_id, "--agent", "dev",
                                    "--agent-id", "dev-actor", "--bump-generation"])
    _assert_no_traceback(rc, "cross-role scope")
    assert rc.returncode == 0
    assert qa_file.read_bytes() == before, "a dev-role reset reached qa's cp-state"

    source = SPEC_CHECK.read_text(encoding="utf-8")
    assert "_enforce_reset_scope" in source and "_enforce_cross_role_scope" in source


def test_cp_checkin_hook_calls_shared_directory_transaction():
    """AC-R02-04, repaired observable.

    The prior observable was 'the hook acquires .cp-checkin.lock', which the
    UNMODIFIED hook already satisfied through its own private helpers -- it
    could not distinguish 'both entrypoints reach the same transaction' from
    'each holds a private scan/clone that happens to open the same lock path'.
    The observable below is FALSE of the baseline: it requires an EXECUTABLE
    call into checkpoint_resources.directory_transaction (an import or a
    docstring mention is not enough) and the absence of the private lock
    helpers it replaced.
    """
    import ast

    source = HOOK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "checkpoint_resources"
    ]
    assert "directory_transaction" in calls, calls
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for private in ("_open_dir_lock", "_release_dir_lock", "_cp_checkin_dir_lock_path"):
        assert private not in names, f"private lock helper {private} still present"
    assert "fail-open on lock failure" not in source, (
        "the fail-open lock branch must be closed: a serialisation primitive "
        "that proceeds unserialised on error cannot underwrite the "
        "no-reassignment invariant"
    )


def test_unlocked_scan_path_is_deleted(tmp_path):
    """AC-R02-11: the dead unlocked scan-pick path must be gone, not merely
    unreferenced, so it cannot be resurrected or re-entered."""
    import ast

    source = SPEC_CHECK.read_text(encoding="utf-8")
    names = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
    assert "_pick_check_in_slot" not in names
    assert "_allocate_instance_id" not in names
    assert "_allocate_instance_id" not in source and "_pick_check_in_slot" not in source
