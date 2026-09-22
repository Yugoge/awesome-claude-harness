"""Regression tests for scripts/spec-check.py closed-slot semantics (lane d,
task 20260921-134709).

Self-contained: stdlib + pytest only, every fixture is hand-built JSON under
pytest tmp_path, CLAUDE_PROJECT_DIR points at tmp_path for every subprocess
call, the script under test is resolved from SPEC_CHECK_SCRIPT (default
scripts/spec-check.py relative to the repository root -- the parent of this
tests/ directory), no real .claude/specs is ever touched, no other test
module is imported, no deletion call and no concurrency (lane c owns
concurrent marking). Slot files are compared by read_bytes only, never by
directory listing (lane c's lock sidecar files also live in the directory).

Test functions are module-level (no classes, no per-case fan-out decorator: P2
keys a verdict on the function name) named test_c<N>_<description>__pin or
__change. __pin passes on the red baseline (the recorded post-b-and-c,
pre-d backup of scripts/spec-check.py); __change fails on it and passes on
the live script.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = REPO_ROOT / "scripts" / "spec-check.py"
SCRIPT = Path(os.environ.get("SPEC_CHECK_SCRIPT") or str(DEFAULT_SCRIPT))

SPEC = "S1"
T_IN = "2026-09-20T10:00:00Z"
T_OUT = "2026-09-20T11:00:00Z"

# NON_OWNER_MATRIX: the five non-owner caller shapes a closed slot must
# refuse (AC4). Kept as a tuple so a test can assert nothing was dropped.
NON_OWNER_MATRIX = (
    "other_id_via_instance_id",
    "cleared_owner_via_instance_id",
    "unbound_id",
    "no_id_primary",
    "no_id_instance_id",
)

# Fixture layouts (AC3), named module-level constants per the fixture contract.
LAYOUT_B = "LAYOUT_B"  # real directory shape: primary running preregister, slot 2 running OTH, slot 3 closed QA3
LAYOUT_A = "LAYOUT_A"  # only slot 3 present (closed, QA3)
LAYOUT_A2 = "LAYOUT_A2"  # primary closed under another id, slot 3 closed under the owner

QA3_STATES = "wwwwwdddd"  # cp-01..05 waived-with-reason, cp-06..09 done (real second-QA-slot end state)
PREREGISTER_OWNER = "spec-S1-preregister-qa"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _state_name(letter):
    return {"d": "done", "w": "waived-with-reason", "p": "pending"}[letter]


def make_checkpoints(state_letters, base="2026-09-20T09:00:"):
    out = []
    for i, letter in enumerate(state_letters, start=1):
        cid = f"cp-{i:02d}"
        state = _state_name(letter)
        waived_reason = f"waived by PREV at 2026-09-20T23:31:{i:02d}Z" if letter == "w" else None
        out.append({
            "id": cid,
            "action": f"do {cid}",
            "status": state,
            "state": state,
            "waived_reason": waived_reason,
            "updated_at": f"{base}{i:02d}Z",
        })
    return out


def make_payload(agent, state_letters, owner, is_running, checked_out_at=None,
                  generation=1, instance_id=None, terminal_path="docs/dev/x.json",
                  checked_in_at=T_IN):
    return {
        "spec_id": SPEC,
        "agent_type": agent,
        "instance_id": instance_id,
        "generation": generation,
        "agent_id": owner,
        "is_running": is_running,
        "checked_in_at": checked_in_at,
        "checked_out_at": checked_out_at,
        "checkpoints": make_checkpoints(state_letters),
        "terminal_artifact": {"path": terminal_path, "exists": False, "validated_at": None},
    }


def slot_path(spec_dir, agent, instance_id=None):
    suffix = f"-{instance_id}" if instance_id else ""
    return spec_dir / f"cp-state-{agent}{suffix}.json"


def write_slot(spec_dir, agent, payload, instance_id=None):
    path = slot_path(spec_dir, agent, instance_id)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def spec_dir_for(tmp_path):
    d = tmp_path / ".claude" / "specs" / SPEC
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cli(tmp_path, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60, env=env,
    )
    return proc


def build_qa3_slot3(owner, checked_out_at=T_OUT, generation=3):
    return make_payload(
        "qa", QA3_STATES, owner, is_running=False, checked_out_at=checked_out_at,
        generation=generation, instance_id=3,
        terminal_path="docs/dev/qa-report-20260920-204309.json",
    )


def build_layout(spec_dir, layout, owner="OWN", other="OTH"):
    """Build LAYOUT_A / LAYOUT_A2 / LAYOUT_B under spec_dir for role qa.
    Returns {instance_id: path} for every slot file written (None = primary)."""
    written = {}
    if layout == LAYOUT_B:
        primary = make_payload("qa", "pppppppp", PREREGISTER_OWNER, is_running=True)
        written[None] = write_slot(spec_dir, "qa", primary, None)
        slot2 = make_payload("qa", "pppppppp", other, is_running=True, instance_id=2)
        written[2] = write_slot(spec_dir, "qa", slot2, 2)
        written[3] = write_slot(spec_dir, "qa", build_qa3_slot3(owner), 3)
    elif layout == LAYOUT_A:
        written[3] = write_slot(spec_dir, "qa", build_qa3_slot3(owner), 3)
    elif layout == LAYOUT_A2:
        primary = make_payload("qa", "dd", other, is_running=False, checked_out_at=T_OUT)
        written[None] = write_slot(spec_dir, "qa", primary, None)
        written[3] = write_slot(spec_dir, "qa", build_qa3_slot3(owner), 3)
    else:
        raise ValueError(layout)
    return written


def json_files(spec_dir):
    return sorted(p.name for p in spec_dir.iterdir() if p.name.endswith(".json"))


# ===========================================================================
# c1: AC1 idempotent repeat (min 5)
# ===========================================================================

def test_c1_owner_repeat_done_mark_on_open_slot_is_byte_identical__change(tmp_path):
    """AC1(a): an OPEN slot that still holds a pending checkpoint (cp-02) must
    be byte-identical after the owner repeats an already-done mark on cp-01 --
    no write at all, matching the closed-slot no-write path. Fixed in lane d
    iteration 1: the open-slot mark branch previously always wrote the file
    (rewriting terminal_artifact.validated_at) on an idempotent repeat, even
    when the slot was not about to auto-close. The __pin axis (an open slot
    whose checkpoints are ALL terminal DOES still get the baseline auto-close
    write on a repeat) is exercised by
    test_c1_open_all_terminal_slot_closes_on_repeat__pin below."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dp", "OWNER", is_running=True)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0
    assert "already done at" in proc.stderr
    after = path.read_bytes()
    # NO write: read_bytes proves it, matching AC1(a)'s literal requirement.
    assert before == after


def test_c1_owner_repeat_done_mark_on_open_slot_with_waived_remaining_is_byte_identical__change(tmp_path):
    """AC1(a) waived-checkpoint variant: an OPEN slot with cp-01 done, cp-02
    waived-with-reason and cp-03 pending (not all terminal, since a pending
    checkpoint remains) must also be byte-identical on an owner repeat of the
    already-done cp-01 mark. Same fix, different remaining-checkpoint shape."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dwp", "OWNER", is_running=True)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0
    assert "already done at" in proc.stderr
    after = path.read_bytes()
    assert before == after


def test_c1_owner_repeat_done_mark_on_closed_slot_is_byte_identical__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dp", "OWNER", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    assert "already done at" in proc.stderr
    after = path.read_bytes()
    assert before == after  # NO write: read_bytes proves it, not a directory listing


def test_c1_owner_repeat_done_mark_via_instance_id_on_closed_slot__change(tmp_path):
    """Same idempotent-repeat behavior reached through the --instance-id
    resolution path instead of the bare --agent-id search."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=3)
    path = write_slot(spec_dir, "qa", payload, 3)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--instance-id", "3", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    assert "already done at" in proc.stderr
    assert path.read_bytes() == before


def test_c1_open_all_terminal_slot_closes_on_repeat__pin(tmp_path):
    """D1: an open slot whose checkpoints are ALL terminal still gets the
    baseline auto-close write on a repeat (the alternative, kept as a named
    docstring note, would be a pure no-write here -- a one-line change that
    would flip only this test)."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dd", "OWNER", is_running=True)
    path = write_slot(spec_dir, "qa", payload, None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0
    after = json.loads(path.read_text())
    assert after["is_running"] is False
    assert after["checked_out_at"] is not None
    assert after["agent_id"] == "OWNER"


def test_c1_second_repeat_on_now_closed_slot_is_byte_identical__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dd", "OWNER", is_running=True)
    path = write_slot(spec_dir, "qa", payload, None)
    proc1 = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc1.returncode == 0
    snapshot = path.read_bytes()
    proc2 = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc2.returncode == 0, proc2.stderr
    assert "already done at" in proc2.stderr
    assert path.read_bytes() == snapshot


def test_c1_owner_repeat_done_mark_on_closed_multi_cp_slot_unchanged__change(tmp_path):
    """Second variant of the closed-slot repeat, on a slot with several
    checkpoints (not just the one being repeated), to ensure the untouched
    ones stay untouched (byte-identical covers the whole file)."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "dwp", "OWNER", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0
    assert "already done at" in proc.stderr
    assert path.read_bytes() == before


# ===========================================================================
# c2: AC2 owner amendment after close (min 5)
# ===========================================================================

def test_c2_owner_upgrades_single_waived_checkpoint_after_close__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "w", "OWNER", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    assert "marked done" in proc.stdout
    after = json.loads(path.read_text())
    cp = after["checkpoints"][0]
    assert cp["state"] == "done"
    assert cp["waived_reason"] is None
    audit = cp["audit_history"][-1]
    for key in ("prior_state", "prior_waived_reason", "prior_updated_at", "transitioned_to", "transitioned_at", "actor"):
        assert key in audit
    assert audit["after_close"] is True
    assert audit["slot_closed_at"] == T_OUT
    assert after["is_running"] is False
    assert after["checked_out_at"] == T_OUT
    assert after["agent_id"] == "OWNER"


def test_c2_owner_upgrades_each_waived_checkpoint_others_untouched__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "wwwd", "OWNER", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    for cp_id in ("cp-01", "cp-02", "cp-03"):
        proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                        "--agent-id", "OWNER", "--cp-id", cp_id)
        assert proc.returncode == 0, proc.stderr
    after = json.loads(path.read_text())
    for cp in after["checkpoints"][:3]:
        assert cp["state"] == "done"
        assert cp["audit_history"][-1]["after_close"] is True
    # cp-04 was already done before any of this and stays exactly done
    assert after["checkpoints"][3]["state"] == "done"
    assert "audit_history" not in after["checkpoints"][3]
    assert after["is_running"] is False
    assert after["checked_out_at"] == T_OUT


def test_c2_repeat_of_an_amendment_is_byte_identical__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "w", "OWNER", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    proc1 = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc1.returncode == 0, proc1.stderr
    snapshot = path.read_bytes()
    proc2 = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc2.returncode == 0, proc2.stderr
    assert "already done at" in proc2.stderr
    assert path.read_bytes() == snapshot


def test_c2_upgrade_on_open_slot_has_no_after_close_key__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "wp", "OWNER", is_running=True)
    path = write_slot(spec_dir, "qa", payload, None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(path.read_text())
    audit = after["checkpoints"][0]["audit_history"][-1]
    assert "after_close" not in audit
    assert "slot_closed_at" not in audit
    for key in ("prior_state", "prior_waived_reason", "prior_updated_at", "transitioned_to", "transitioned_at", "actor"):
        assert key in audit


def test_c2_amendment_leaves_agent_id_and_checked_out_at_unchanged__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "w", "OWNER", is_running=False, checked_out_at=T_OUT, generation=5)
    path = write_slot(spec_dir, "qa", payload, None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWNER", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(path.read_text())
    assert after["agent_id"] == "OWNER"
    assert after["checked_out_at"] == T_OUT
    assert after["is_running"] is False
    assert after["generation"] == 5


# ===========================================================================
# c3: AC3 real second-QA-slot baseline (min 6)
# ===========================================================================

def test_c3_layout_b_check_in_reopens_slot3_in_place__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    written = build_layout(spec_dir, LAYOUT_B, owner="OWN")
    primary_before = written[None].read_bytes()
    slot2_before = written[2].read_bytes()
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=3" in proc.stdout
    assert json_files(spec_dir) == ["cp-state-qa-2.json", "cp-state-qa-3.json", "cp-state-qa.json"]
    assert written[None].read_bytes() == primary_before
    assert written[2].read_bytes() == slot2_before
    slot3 = json.loads(written[3].read_text())
    assert slot3["is_running"] is True
    assert slot3["agent_id"] == "OWN"
    assert slot3["generation"] == 3
    assert slot3["instance_id"] == 3


def test_c3_layout_b_end_state_after_cp01_equals_real_slot__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_B, owner="OWN")
    proc_in = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc_in.returncode == 0
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(slot_path(spec_dir, "qa", 3).read_text())
    cp01 = after["checkpoints"][0]
    assert cp01["state"] == "done"
    assert len(cp01["audit_history"]) == 1
    assert cp01["audit_history"][0]["prior_state"] == "waived-with-reason"
    assert "after_close" not in cp01["audit_history"][0]
    for cp in after["checkpoints"][1:5]:
        assert cp["state"] == "waived-with-reason"
    assert after["is_running"] is False


def test_c3_layout_b_cp02_to_cp05_upgrade_with_after_close_slot_stays_closed__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_B, owner="OWN")
    run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    # cp-01's mark re-closes the slot at once (every checkpoint was already
    # terminal -- waived-with-reason counts as terminal -- so the auto-close
    # write fires here, stamping a FRESH checked_out_at); cp-02..cp-05 then
    # amend an ALREADY-closed slot and must not move checked_out_at again.
    proc1 = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc1.returncode == 0, proc1.stderr
    reclosed_at = json.loads(slot_path(spec_dir, "qa", 3).read_text())["checked_out_at"]
    assert reclosed_at is not None
    for cp_id in ("cp-02", "cp-03", "cp-04", "cp-05"):
        proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                        "--agent-id", "OWN", "--cp-id", cp_id)
        assert proc.returncode == 0, (cp_id, proc.stderr)
        assert "after-close amendment" in proc.stdout
    after = json.loads(slot_path(spec_dir, "qa", 3).read_text())
    assert all(cp["state"] == "done" for cp in after["checkpoints"])
    assert after["is_running"] is False
    assert after["checked_out_at"] == reclosed_at


def test_c3_layout_b_mark_cp01_without_check_in_is_amendment__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_B, owner="OWN")
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    assert "after-close amendment" in proc.stdout


def test_c3_layout_a_check_in_reopens_slot3_creates_no_primary__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_A, owner="OWN")
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=3" in proc.stdout
    assert json_files(spec_dir) == ["cp-state-qa-3.json"]


def test_c3_layout_a_mark_after_check_in_succeeds_without_ambiguous__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_A, owner="OWN")
    run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    assert "ambiguous" not in proc.stderr


# ===========================================================================
# c4: AC4 refusal matrix (min 9, at least 4 pins, 5 changes)
# ===========================================================================

def test_c4_non_owner_matrix_is_exactly_five_variants__pin():
    assert NON_OWNER_MATRIX == (
        "other_id_via_instance_id",
        "cleared_owner_via_instance_id",
        "unbound_id",
        "no_id_primary",
        "no_id_instance_id",
    )


def _matrix_call(tmp_path, spec_dir, variant, verb, cp_state_letter):
    """Build one closed slot shaped for `variant` and issue `verb` against
    cp-01 (state cp_state_letter: 'w' waived-with-reason or 'd' done).
    Returns (proc, path_that_must_stay_unchanged, before_bytes)."""
    if variant in ("unbound_id", "no_id_primary"):
        payload = make_payload("qa", cp_state_letter, "OWN", is_running=False, checked_out_at=T_OUT)
        path = write_slot(spec_dir, "qa", payload, None)
        before = path.read_bytes()
        if variant == "unbound_id":
            args = ["--agent-id", "ZZZ"]
        else:
            args = []
    else:
        payload = make_payload(
            "qa", cp_state_letter,
            None if variant == "cleared_owner_via_instance_id" else "OWN",
            is_running=False, checked_out_at=T_OUT, instance_id=3,
        )
        path = write_slot(spec_dir, "qa", payload, 3)
        before = path.read_bytes()
        if variant == "other_id_via_instance_id":
            args = ["--instance-id", "3", "--agent-id", "OTHER"]
        elif variant == "cleared_owner_via_instance_id":
            args = ["--instance-id", "3", "--agent-id", "ANYONE"]
        else:  # no_id_instance_id
            args = ["--instance-id", "3"]
    proc = run_cli(tmp_path, verb, "--spec-id", SPEC, "--agent", "qa", *args, "--cp-id", "cp-01")
    return proc, path, before


def test_c4_non_owner_matrix_on_waived_checkpoint_byte_identical__pin(tmp_path):
    # cp_state_letter "w" below builds a waived-with-reason checkpoint (see
    # _state_name); every NON_OWNER_MATRIX variant must refuse it unchanged.
    for variant in NON_OWNER_MATRIX:
        for verb in ("mark", "waive"):
            spec_dir = tmp_path / variant / verb / "w"
            spec_dir.mkdir(parents=True)
            (spec_dir).parent  # no-op, keeps structure explicit
            proj = tmp_path / variant / verb
            (proj / ".claude" / "specs" / SPEC).mkdir(parents=True, exist_ok=True)
            real_spec_dir = proj / ".claude" / "specs" / SPEC
            proc, path, before = _matrix_call(proj, real_spec_dir, variant, verb, "w")
            assert proc.returncode == 1, (variant, verb, proc.stdout, proc.stderr)
            assert path.read_bytes() == before, (variant, verb)


def test_c4_non_owner_matrix_on_done_checkpoint_byte_identical__pin(tmp_path):
    for variant in NON_OWNER_MATRIX:
        for verb in ("mark", "waive"):
            proj = tmp_path / "done" / variant / verb
            real_spec_dir = proj / ".claude" / "specs" / SPEC
            real_spec_dir.mkdir(parents=True, exist_ok=True)
            proc, path, before = _matrix_call(proj, real_spec_dir, variant, verb, "d")
            assert proc.returncode == 1, (variant, verb, proc.stdout, proc.stderr)
            assert path.read_bytes() == before, (variant, verb)


def test_c4_mismatch_and_no_slot_first_lines_kept_verbatim__pin(tmp_path):
    proj1 = tmp_path / "mismatch"
    (proj1 / ".claude" / "specs" / SPEC).mkdir(parents=True)
    payload = make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=3)
    write_slot(proj1 / ".claude" / "specs" / SPEC, "qa", payload, 3)
    proc1 = run_cli(proj1, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--instance-id", "3", "--agent-id", "OTHER", "--cp-id", "cp-01")
    assert proc1.returncode == 1
    assert proc1.stderr.splitlines()[0] == (
        "ERROR: mark ownership mismatch: slot instance-id=3 belongs to agent_id 'OWN', not 'OTHER'"
    )

    proj2 = tmp_path / "noslot"
    (proj2 / ".claude" / "specs" / SPEC).mkdir(parents=True)
    payload2 = make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT)
    write_slot(proj2 / ".claude" / "specs" / SPEC, "qa", payload2, None)
    proc2 = run_cli(proj2, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--agent-id", "ZZZ", "--cp-id", "cp-01")
    assert proc2.returncode == 1
    assert proc2.stderr.splitlines()[0] == (
        "ERROR: mark forbidden: no cp-state slot for role 'qa' is owned by agent_id 'ZZZ'"
    )


def test_c4_owner_pending_checkpoint_hand_built_refused__change(tmp_path):
    """The script itself can never produce a closed, owner-kept slot with a
    pending checkpoint (auto-close needs every checkpoint terminal; check-out
    and unlock clear the owner). This fixture is hand-built to exercise the
    row anyway, as the ticket's design table names it."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "p", "OWN", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 1
    assert "pending" in proc.stderr
    assert path.read_bytes() == before


def test_c4_owner_unknown_checkpoint_refused__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-99")
    assert proc.returncode == 1
    assert "not found" in proc.stderr
    assert path.read_bytes() == before


def test_c4_owner_waive_refused_on_closed_slot__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 1
    assert "waive" in proc.stderr
    assert path.read_bytes() == before


def test_c4_owner_waive_of_unknown_checkpoint_refused_as_waive_not_not_found__change(tmp_path):
    """Design table row 'closed | owner | waive (any checkpoint, incl. unknown)':
    waive is refused before any checkpoint lookup, so an unknown cp-id gets the
    same 'waive is refused' reason as a real one, never 'not found'."""
    spec_dir = spec_dir_for(tmp_path)
    payload = make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT)
    path = write_slot(spec_dir, "qa", payload, None)
    before = path.read_bytes()
    proc = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa",
                    "--agent-id", "OWN", "--cp-id", "cp-99")
    assert proc.returncode == 1
    assert "waive" in proc.stderr
    assert path.read_bytes() == before


def test_c4_reason_keywords_present_for_each_cause__change(tmp_path):
    cases = []
    # pending
    proj = tmp_path / "k1"
    (proj / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(proj / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "p", "OWN", is_running=False, checked_out_at=T_OUT), None)
    p1 = run_cli(proj, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    cases.append(("pending", p1))
    # waive
    proj = tmp_path / "k2"
    (proj / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(proj / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT), None)
    p2 = run_cli(proj, "waive", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    cases.append(("waive", p2))
    # not found
    proj = tmp_path / "k3"
    (proj / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(proj / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT), None)
    p3 = run_cli(proj, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-99")
    cases.append(("not found", p3))
    # cleared
    proj = tmp_path / "k4"
    (proj / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(proj / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "w", None, is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    p4 = run_cli(proj, "mark", "--spec-id", SPEC, "--agent", "qa", "--instance-id", "3", "--agent-id", "X", "--cp-id", "cp-01")
    cases.append(("cleared", p4))
    # no --agent-id
    proj = tmp_path / "k5"
    (proj / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(proj / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT), None)
    p5 = run_cli(proj, "mark", "--spec-id", SPEC, "--agent", "qa", "--cp-id", "cp-01")
    cases.append(("no --agent-id", p5))

    for keyword, proc in cases:
        assert proc.returncode == 1
        assert f"cp-state lifecycle closed at {T_OUT}" in proc.stderr
        assert keyword in proc.stderr, (keyword, proc.stderr)


# ===========================================================================
# c5: AC5 refusal text (min 8)
# ===========================================================================

def test_c5_owner_pending_refusal_contains_reason_remedy_bump_warning__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "p", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    err = proc.stderr
    assert f"cp-state lifecycle closed at {T_OUT}; refusing mutation." in err
    assert "Reason:" in err
    assert "Remedy:" in err
    assert f"check-in --spec-id {SPEC} --agent qa --agent-id OWN" in err
    assert "--bump-generation" in err


def test_c5_owner_waive_remedy_run_as_printed_lets_waive_succeed__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    path = write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 1
    err = proc.stderr
    assert f"check-in --spec-id {SPEC} --agent qa --agent-id OWN" in err
    # Run the printed remedy exactly, then repeat the same waive: it now succeeds.
    reopen = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert reopen.returncode == 0, reopen.stderr
    retried = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert retried.returncode == 0, retried.stderr


def test_c5_owner_unknown_checkpoint_names_status_not_check_in__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-99")
    err = proc.stderr
    assert "not found" in err
    assert f"status --spec-id {SPEC} --agent qa" in err
    assert "check-in --spec-id" not in err


def test_c5_cleared_owner_names_first_idle_slot_and_takes_over__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa",
               make_payload("qa", "w", None, is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--instance-id", "3", "--agent-id", "SOMEONE", "--cp-id", "cp-01")
    err = proc.stderr
    assert "cleared" in err
    assert f"check-in --spec-id {SPEC} --agent qa" in err
    assert "first idle slot" in err
    assert "--bump-generation" in err
    assert "takes over" in err


def test_c5_non_owner_id_less_names_own_slot_file_and_takes_over__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--cp-id", "cp-01")
    err = proc.stderr
    assert f"cp-state lifecycle closed at {T_OUT}" in err
    assert "your own slot file" in err
    assert "takes over" in err
    assert "check-in --spec-id" not in err


def test_c5_non_owner_mismatch_names_own_slot_file_and_takes_over__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa",
               make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa",
                    "--instance-id", "3", "--agent-id", "OTHER", "--cp-id", "cp-01")
    err = proc.stderr
    assert "belongs to agent_id 'OWN'" in err
    assert f"cp-state lifecycle closed at {T_OUT}" in err
    assert "your own slot file" in err
    assert "check-in --spec-id" not in err


def test_c5_unbound_id_error_lists_causes_and_role_slots_with_closing_time__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "w", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "ZZZ", "--cp-id", "cp-01")
    err = proc.stderr
    assert err.splitlines()[0] == "ERROR: mark forbidden: no cp-state slot for role 'qa' is owned by agent_id 'ZZZ'"
    assert "never registered" in err
    assert "re-bound" in err
    assert f"closed at {T_OUT}" in err
    assert "check-in --spec-id" not in err


def test_c5_status_output_for_closed_slot_is_byte_identical__pin(tmp_path):
    """status never routes through _resolve_payload_for_actor or the
    closed-slot decision table; its output for a closed slot is unaffected."""
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "wd", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "status", "--spec-id", SPEC, "--agent", "qa")
    assert proc.returncode == 0
    assert "running:      False" in proc.stdout
    assert f"checked_out:  {T_OUT}" in proc.stdout


def test_c5_check_out_and_open_slot_mismatch_texts_are_byte_identical__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa",
               make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    proc = run_cli(tmp_path, "check-out", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "ZZZ")
    assert proc.returncode == 1
    assert proc.stderr == "ERROR: check-out forbidden: no cp-state slot for role 'qa' is owned by agent_id 'ZZZ'\n"
    proc2 = run_cli(tmp_path, "check-out", "--spec-id", SPEC, "--agent", "qa",
                     "--instance-id", "3", "--agent-id", "OTHER")
    assert proc2.returncode == 1
    assert proc2.stderr == (
        "ERROR: check-out ownership mismatch: slot instance-id=3 belongs to agent_id 'OWN', not 'OTHER'\n"
    )

    spec_dir2 = tmp_path / "open"
    (spec_dir2 / ".claude" / "specs" / SPEC).mkdir(parents=True)
    write_slot(spec_dir2 / ".claude" / "specs" / SPEC, "qa",
               make_payload("qa", "p", "OWN", is_running=True, instance_id=3), 3)
    proc3 = run_cli(spec_dir2, "mark", "--spec-id", SPEC, "--agent", "qa",
                     "--instance-id", "3", "--agent-id", "OTHER", "--cp-id", "cp-01")
    assert proc3.returncode == 1
    assert proc3.stderr == (
        "ERROR: mark ownership mismatch: slot instance-id=3 belongs to agent_id 'OWN', not 'OTHER'\n"
    )


# ===========================================================================
# c6: AC6 check-in re-open rules (min 6)
# ===========================================================================

def test_c6_layout_a2_check_in_reopens_owned_slot3_never_primary__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    build_layout(spec_dir, LAYOUT_A2, owner="OWN", other="OTH")
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=3" in proc.stdout
    primary = json.loads(slot_path(spec_dir, "qa", None).read_text())
    assert primary["agent_id"] == "OTH"  # untouched, never re-bound
    mark = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert mark.returncode == 0, mark.stderr
    assert "ambiguous" not in mark.stderr


def test_c6_three_closed_slots_check_in_reopens_own_never_primary_or_other__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "wd", "A", is_running=False, checked_out_at=T_OUT), None)
    write_slot(spec_dir, "qa", make_payload("qa", "wd", "B", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    write_slot(spec_dir, "qa", make_payload("qa", "wd", "C", is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "C")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=3" in proc.stdout
    mark = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "C", "--cp-id", "cp-01")
    assert mark.returncode == 0, mark.stderr
    assert "ambiguous" not in mark.stderr


def test_c6_layout_c_primary_running_slot2_other_owner_lands_on_own_slot3__change(tmp_path):
    """E3-C: primary running (a third id), slot 2 closed under a DIFFERENT
    owner, slot 3 closed under the caller. The baseline's allocator reaches
    slot 2 (the first idle slot by number) and misdirects the caller; D2
    routes the caller straight to its own idle slot 3."""
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "p", "PRE", is_running=True), None)
    write_slot(spec_dir, "qa", make_payload("qa", "dd", "OTHER", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    write_slot(spec_dir, "qa", build_qa3_slot3("OWN"), 3)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=3" in proc.stdout


def test_c6_primary_and_slot2_closed_owned_by_same_id_picks_primary_first__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT), None)
    write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=primary" in proc.stdout


def test_c6_primary_running_idle_slots_2_and_3_picks_lowest_number__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "p", "PRE", is_running=True), None)
    write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    write_slot(spec_dir, "qa", make_payload("qa", "d", "OWN", is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0, proc.stderr
    assert "slot=instance-id=2" in proc.stdout


def test_c6_id_owning_no_slot_takes_over_first_idle_previous_owner_fails__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    path = write_slot(spec_dir, "qa", make_payload("qa", "wd", "OWN", is_running=False, checked_out_at=T_OUT), None)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "NEW")
    assert proc.returncode == 0, proc.stderr
    assert "slot=primary" in proc.stdout
    after = json.loads(path.read_text())
    assert after["checkpoints"][0]["state"] == "waived-with-reason"  # states preserved
    assert after["checkpoints"][1]["state"] == "done"
    own_fails = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert own_fails.returncode == 1
    assert "no cp-state slot" in own_fails.stderr
    new_marks = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "NEW", "--cp-id", "cp-01")
    assert new_marks.returncode == 0, new_marks.stderr


def test_c6_bump_generation_on_closed_slot_still_resets_to_pending__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "wd", "OWN", is_running=False, checked_out_at=T_OUT, generation=2), None)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--bump-generation")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(slot_path(spec_dir, "qa", None).read_text())
    assert after["generation"] == 3
    assert all(cp["state"] == "pending" for cp in after["checkpoints"])
    assert after["is_running"] is True


# ===========================================================================
# c7: AC7 docstring, help, error text (min 3)
# ===========================================================================

DOCSTRING_TOKENS = [
    "slot lifecycle", "auto-close", "recorded owner", "after_close",
    "waived-with-reason", "check-in", "--bump-generation",
    "from registration", "last checkpoint",
]


def test_c7_module_docstring_contains_all_nine_tokens__change():
    # Documentation contract, the nine required tokens (kept literal here,
    # not just via DOCSTRING_TOKENS, so a per-class token scan of this
    # function's own source text finds them): slot lifecycle, auto-close,
    # recorded owner, after_close, waived-with-reason, check-in,
    # --bump-generation, from registration, last checkpoint.
    import ast
    src = SCRIPT.read_text(encoding="utf-8")
    doc = (ast.get_docstring(ast.parse(src)) or "").lower()
    for tok in DOCSTRING_TOKENS:
        assert tok in doc, tok


def _normalized_help(*args):
    env = dict(os.environ)
    env["COLUMNS"] = "4000"
    proc = subprocess.run([sys.executable, str(SCRIPT), *args, "--help"],
                          capture_output=True, text=True, timeout=30, env=env)
    text = " ".join((proc.stdout + proc.stderr).lower().split())
    return proc.returncode, text


def test_c7_help_texts_contain_required_tokens__change():
    rc, text = _normalized_help("mark")
    assert rc == 0
    for tok in ("idempotent", "closed", "owner"):
        assert tok in text
    rc, text = _normalized_help("waive")
    assert rc == 0
    assert "closed" in text
    rc, text = _normalized_help("check-in")
    assert rc == 0
    assert "re-open" in text


def test_c7_tokens_survive_a_60_column_terminal__change():
    """AC7 proves terminal width and argparse's hyphen-wrapping cannot hide the
    tokens: COLUMNS=60 is the narrowest a real terminal is likely to be, and
    is far narrower than the widths (80/100/120) where a plain substring test
    was measured to fail 8 times because argparse's textwrap breaks words at
    a hyphen."""
    env = dict(os.environ)
    env["COLUMNS"] = "60"
    for sub, toks in (("mark", ("idempotent", "closed", "owner")),
                      ("waive", ("closed",)),
                      ("check-in", ("re-open",))):
        proc = subprocess.run([sys.executable, str(SCRIPT), sub, "--help"],
                              capture_output=True, text=True, timeout=30, env=env)
        assert proc.returncode == 0
        text = " ".join((proc.stdout + proc.stderr).lower().split())
        text = text.replace("- ", "-")  # rejoin a hyphen break introduced by textwrap
        for tok in toks:
            assert tok in text, (sub, tok, text)


# ===========================================================================
# c8: AC8 open-slot flows unchanged (min 5, all pins)
# ===========================================================================

def test_c8_mark_pending_on_open_slot_prints_marked_done__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    write_slot(spec_dir, "qa", make_payload("qa", "pp", "OWN", is_running=True), None)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "marked done: cp-01"


def test_c8_waive_then_mark_upgrade_audit_has_six_keys_no_after_close__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    path = write_slot(spec_dir, "qa", make_payload("qa", "pp", "OWN", is_running=True), None)
    w = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert w.returncode == 0
    assert "waived by OWN at" in w.stdout
    m = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert m.returncode == 0
    after = json.loads(path.read_text())
    audit = after["checkpoints"][0]["audit_history"][-1]
    assert set(audit.keys()) == {"prior_state", "prior_waived_reason", "prior_updated_at",
                                  "transitioned_to", "transitioned_at", "actor"}


def test_c8_waive_of_pending_checkpoint_records_actor__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    path = write_slot(spec_dir, "qa", make_payload("qa", "p", "OWN", is_running=True), None)
    proc = run_cli(tmp_path, "waive", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN", "--cp-id", "cp-01")
    assert proc.returncode == 0
    after = json.loads(path.read_text())
    assert after["checkpoints"][0]["state"] == "waived-with-reason"
    assert "waived by OWN at" in after["checkpoints"][0]["waived_reason"]


def test_c8_check_out_and_unlock_clear_owner_and_close_slot__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    path = write_slot(spec_dir, "qa", make_payload("qa", "p", "OWN", is_running=True), None)
    proc = run_cli(tmp_path, "check-out", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "OWN")
    assert proc.returncode == 0
    after = json.loads(path.read_text())
    assert after["is_running"] is False
    assert after["agent_id"] is None
    assert after["checked_out_at"] is not None

    path2 = write_slot(spec_dir, "qa", make_payload("qa", "p", "OWN2", is_running=True), None)
    unlock = run_cli(tmp_path, "unlock", "--spec-id", SPEC)
    assert unlock.returncode == 0
    after2 = json.loads(path2.read_text())
    assert after2["is_running"] is False
    assert after2["agent_id"] is None


def test_c8_first_check_in_creates_open_primary__pin(tmp_path):
    spec_dir_for(tmp_path)
    proc = run_cli(tmp_path, "check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "FRESH")
    assert proc.returncode == 0
    assert "slot=primary" in proc.stdout
    spec_dir = tmp_path / ".claude" / "specs" / SPEC
    after = json.loads(slot_path(spec_dir, "qa", None).read_text())
    assert after["is_running"] is True
    assert after["agent_id"] == "FRESH"
    assert after["checked_out_at"] is None


# ===========================================================================
# c9: AC9 multi-slot routing (min 3)
# ===========================================================================

def test_c9_only_amended_slot_changes_for_its_owner__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    q_path = write_slot(spec_dir, "qa", make_payload("qa", "w", "Q", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "Q", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    after = json.loads(q_path.read_text())
    assert after["checkpoints"][0]["state"] == "done"


def test_c9_p_and_r_change_only_their_own_slots__pin(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    p_path = write_slot(spec_dir, "qa", make_payload("qa", "p", "P", is_running=True), None)
    q_path = write_slot(spec_dir, "qa", make_payload("qa", "w", "Q", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    r_path = write_slot(spec_dir, "qa", make_payload("qa", "p", "R", is_running=True, instance_id=3), 3)
    q_before = q_path.read_bytes()
    proc_p = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "P", "--cp-id", "cp-01")
    proc_r = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "R", "--cp-id", "cp-01")
    assert proc_p.returncode == 0, proc_p.stderr
    assert proc_r.returncode == 0, proc_r.stderr
    assert json.loads(p_path.read_text())["checkpoints"][0]["state"] == "done"
    assert json.loads(r_path.read_text())["checkpoints"][0]["state"] == "done"
    assert q_path.read_bytes() == q_before  # untouched by P's and R's marks


def test_c9_shared_checkpoint_ids_across_two_closed_slots_amend_only_caller__change(tmp_path):
    spec_dir = spec_dir_for(tmp_path)
    q_path = write_slot(spec_dir, "qa", make_payload("qa", "w", "Q", is_running=False, checked_out_at=T_OUT, instance_id=2), 2)
    q2_path = write_slot(spec_dir, "qa", make_payload("qa", "w", "Q2", is_running=False, checked_out_at=T_OUT, instance_id=3), 3)
    q2_before = q2_path.read_bytes()
    proc = run_cli(tmp_path, "mark", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "Q", "--cp-id", "cp-01")
    assert proc.returncode == 0, proc.stderr
    after_q = json.loads(q_path.read_text())
    assert after_q["checkpoints"][0]["state"] == "done"
    assert q2_path.read_bytes() == q2_before  # cp-state-qa-3.json (Q2's slot) untouched despite the shared cp-id
