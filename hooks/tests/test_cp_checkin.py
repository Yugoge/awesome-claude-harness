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
