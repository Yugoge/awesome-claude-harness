"""Adversarial tests for the closed Lane B H-B v3/fan-in verifier."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = (
    Path(__file__).parents[2]
    if "hooks/tests" in str(Path(__file__))
    else Path(os.environ.get("LANEB_PROJECT_ROOT", ".")).resolve()
)
GATE = Path(
    os.environ.get("LANEB_GATE_CANDIDATE", ROOT / "scripts/laneb-integration-gate.py")
)
CONTRACT = ROOT / "docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json"
SPEC = importlib.util.spec_from_file_location("laneb_gate", GATE)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _fresh(**updates: object) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    value = {
        "snapshot_id": "a" * 64,
        "observed_at": stamp(now - dt.timedelta(seconds=1)),
        "generated_at": stamp(now - dt.timedelta(milliseconds=500)),
        "expires_at": stamp(now + dt.timedelta(seconds=5)),
        "window_seconds": 6,
        "monotonic_start_ns": 10,
        "monotonic_end_ns": 20,
    }
    value.update(updates)
    return value


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--project-root", str(root), *args],
        text=True,
        capture_output=True,
        timeout=20,
    )


def _contract() -> dict:
    return json.loads(CONTRACT.read_text())


def test_strict_json_rejects_duplicate_and_nonfinite() -> None:
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b"\xff"):
        with pytest.raises(m.GateError):
            m.strict_loads(raw)


def test_canonical_json_is_sorted_compact_utf8_and_finite() -> None:
    assert m._canonical({"z": 1, "a": "值"}) == b'{"a":"\xe5\x80\xbc","z":1}'
    with pytest.raises(m.GateError):
        m._canonical({"x": float("nan")})


@pytest.mark.parametrize(
    "changes",
    [
        {"window_seconds": 16},
        {"window_seconds": True},
        {"monotonic_start_ns": 20, "monotonic_end_ns": 10},
        {"snapshot_id": "A" * 64},
        {
            "observed_at": "2999-01-01T00:00:00Z",
            "generated_at": "2999-01-01T00:00:00Z",
            "expires_at": "2999-01-01T00:00:01Z",
        },
        {
            "observed_at": "2000-01-01T00:00:00Z",
            "generated_at": "2000-01-01T00:00:00Z",
            "expires_at": "2000-01-01T00:00:01Z",
        },
    ],
)
def test_freshness_fail_closed(changes: dict) -> None:
    with pytest.raises(m.GateError) as error:
        m.validate_freshness(_fresh(**changes))
    assert error.value.code == "freshness_invalid"


def test_freshness_positive() -> None:
    m.validate_freshness(_fresh())


@pytest.mark.parametrize("value", ["/etc/passwd", "../x", "a/../x", "./x", "a\\b", ""])
def test_capture_rejects_absolute_traversal_and_ambiguous_paths(
    tmp_path: Path, value: str
) -> None:
    with m.CaptureSet(tmp_path) as captures:
        with pytest.raises(m.GateError):
            captures.capture(value)


def test_capture_rejects_final_and_ancestor_symlink(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "value").write_text("x")
    (tmp_path / "leaf").symlink_to(tmp_path / "real" / "value")
    (tmp_path / "ancestor").symlink_to(tmp_path / "real", target_is_directory=True)
    with m.CaptureSet(tmp_path) as captures:
        for value in ("leaf", "ancestor/value"):
            with pytest.raises(m.GateError):
                captures.capture(value)


def test_capture_detects_same_descriptor_byte_drift(tmp_path: Path) -> None:
    path = tmp_path / "value"
    path.write_bytes(b"before")
    with m.CaptureSet(tmp_path) as captures:
        item = captures.capture("value")
        assert item and item.sha256 == _sha(b"before")
        path.write_bytes(b"after!")
        with pytest.raises(m.GateError) as error:
            captures.revalidate()
        assert error.value.code == "stable_fd_drift"


def test_capture_records_mode_device_inode_and_size(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    path.chmod(0o640)
    with m.CaptureSet(tmp_path) as captures:
        item = captures.capture("x")
        assert item and (item.mode, item.size) == ("0640", 3)
        assert item.device > 0 and item.inode > 0


def test_derive_paths_is_per_kind_and_exact() -> None:
    contract = _contract()
    gate = m.derive_paths(contract, "GATE_REPAIR_HB3", "a000006")
    final = m.derive_paths(contract, "FINAL_FAN_IN", "a000006")
    pol = m.derive_paths(contract, "POL_EXTERNAL", "a000006")
    assert len(gate) == 14 and len(final) == 11 and len(pol) == 2
    assert gate["dev_report"].endswith("repair-a000006.json")
    assert final["envelope"].endswith("v2.a000006.json")
    assert (
        "a000006" in pol["phase_record_template"]
        and "p000001" in pol["phase_record_template"]
    )
    with pytest.raises(m.GateError):
        m.derive_paths(contract, "GATE_REPAIR_HB3", "a6")


def _event(
    contract: dict,
    *,
    sequence: int,
    kind: str,
    attempt: str,
    event_type: str,
    outcome: str,
    previous: str | None,
    predecessor_state: str = "NO_EVENT_FOR_THIS_ATTEMPT",
) -> dict:
    event = {
        "schema_version": 3,
        "record_type": "lane_b_attempt_registry_event.v3",
        "event_sequence": sequence,
        "previous_event_sha256": previous,
        "event_type": event_type,
        "attempt_kind": kind,
        "attempt_id": attempt,
        "attempt_sequence": int(attempt[1:]),
        "transaction_id": f"tx-{kind}-{attempt}",
        "nonce": hashlib.sha256(f"{kind}:{attempt}".encode()).hexdigest(),
        "identity": {
            "session_id": m.SESSION_ID,
            "spec_id": m.SPEC_ID,
            "cycle_id": 1,
            "lane_id": "LANE-B",
            "pipeline_id": "pipeline-5" if kind == "POL_EXTERNAL" else "pipeline-0",
            "task_id": "fixture",
        },
        "owner_role": "same_spec_parent",
        "template_version": "lane_b_attempt_paths.v3",
        "derived_paths": m.derive_paths(contract, kind, attempt),
        "precondition_manifest_sha256": "b" * 64,
        "event_at": "2026-08-12T00:00:00Z",
        "outcome": outcome,
        "integrity": {
            "event_payload_sha256": "0" * 64,
            "canonicalization": "UTF-8 sorted-key compact JSON excluding only event_payload_sha256; LF is outside payload",
        },
    }
    payload = copy.deepcopy(event)
    del payload["integrity"]["event_payload_sha256"]
    event["integrity"]["event_payload_sha256"] = m.canonical_sha(payload)
    return event


def test_registry_per_kind_same_token_is_legal(tmp_path: Path) -> None:
    contract = _contract()
    rows = []
    previous = None
    for sequence, kind in enumerate(
        ("GATE_REPAIR_HB3", "FINAL_FAN_IN", "POL_EXTERNAL"), 1
    ):
        row = _event(
            contract,
            sequence=sequence,
            kind=kind,
            attempt="a000001",
            event_type="ALLOCATED",
            outcome="none",
            previous=previous,
        )
        rows.append(row)
        previous = _sha(_canonical(row))
    data = b"".join(_canonical(row) + b"\n" for row in rows)
    path = tmp_path / "registry.jsonl"
    path.write_bytes(data)
    with m.CaptureSet(tmp_path) as captures:
        cap = captures.capture("registry.jsonl")
        states = m.replay_registry(contract, cap)
    assert set(states) == {
        (kind, "a000001")
        for kind in ("GATE_REPAIR_HB3", "FINAL_FAN_IN", "POL_EXTERNAL")
    }


@pytest.mark.parametrize(
    "mutation", ["sequence", "previous", "path", "pipeline", "digest", "noncanonical"]
)
def test_registry_replay_fork_gap_and_shape_deny(tmp_path: Path, mutation: str) -> None:
    contract = _contract()
    row = _event(
        contract,
        sequence=1,
        kind="GATE_REPAIR_HB3",
        attempt="a000001",
        event_type="ALLOCATED",
        outcome="none",
        previous=None,
    )
    if mutation == "sequence":
        row["event_sequence"] = 2
    elif mutation == "previous":
        row["previous_event_sha256"] = "c" * 64
    elif mutation == "path":
        row["derived_paths"]["dev_report"] = "wrong"
    elif mutation == "pipeline":
        row["identity"]["pipeline_id"] = "pipeline-5"
    elif mutation == "digest":
        row["integrity"]["event_payload_sha256"] = "d" * 64
    raw = _canonical(row)
    if mutation == "noncanonical":
        raw = json.dumps(row, indent=2).encode()
    (tmp_path / "r").write_bytes(raw + b"\n")
    with m.CaptureSet(tmp_path) as captures:
        cap = captures.capture("r")
        with pytest.raises(m.GateError):
            m.replay_registry(contract, cap)


def test_hb3_result_rows_are_exact_ordered_closed_set() -> None:
    contract = _contract()
    rows = m._result_rows(contract)
    assert len(rows) == 20
    assert [row["ordinal"] for row in rows] == list(range(1, 21))
    assert [row["id"] for row in rows] == [f"HB3-N{i:02d}" for i in range(1, 21)]
    assert [row["observed_code"] for row in rows] == list(m.HB3_CODES)
    assert all(
        row["status"] == "pass"
        and row["authority"] is False
        and row["authorizes"] == []
        for row in rows
    )


@pytest.mark.parametrize("index", range(20))
def test_hb3_result_schema_rejects_each_wrong_code(index: int) -> None:
    contract = _contract()
    rows = m._result_rows(contract)
    rows[index]["observed_code"] = "wrong"
    with pytest.raises(m.GateError) as error:
        m._schema(
            rows,
            contract["h_b_v3_closed_contract"]["hb3_result_set_schema"],
            "h_b_v3_verifier_invalid",
        )
    assert error.value.code == "h_b_v3_verifier_invalid"


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "swap", "case", "type", "alias"]
)
def test_hb3_result_set_schema_rejects_structure_mutations(mutation: str) -> None:
    contract = _contract()
    rows = m._result_rows(contract)
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "swap":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "case":
        rows[0]["status"] = "PASS"
    elif mutation == "type":
        rows[0]["authority"] = 0
    else:
        rows[0]["code"] = rows[0]["expected_code"]
    with pytest.raises(m.GateError):
        m._schema(
            rows,
            contract["h_b_v3_closed_contract"]["hb3_result_set_schema"],
            "h_b_v3_verifier_invalid",
        )


def test_readiness_decision_exact_nine_all_false() -> None:
    contract = _contract()
    value = {
        "H_B_v3_current": False,
        "POL_start_allowed": False,
        "BIND_start_allowed": False,
        "fan_in_allowed": False,
        "lane_completion_allowed": False,
        "spec_completion_allowed": False,
        "close_allowed": False,
        "commit_allowed": False,
        "authorizes": [],
    }
    m._schema(
        value,
        contract["h_b_v3_closed_contract"]["readiness_decision_schema"],
        "h_b_v3_closed_schema_invalid",
    )
    for key in list(value):
        broken = copy.deepcopy(value)
        broken[key] = True if key != "authorizes" else ["x"]
        with pytest.raises(m.GateError):
            m._schema(
                broken,
                contract["h_b_v3_closed_contract"]["readiness_decision_schema"],
                "h_b_v3_closed_schema_invalid",
            )


def test_marker_schema_has_single_closed_transaction_and_predecessor_language() -> None:
    contract = _contract()
    schema = contract["h_b_v3_closed_contract"]["external_commit_marker"][
        "embedded_json_schema"
    ]
    assert set(schema["$defs"]["marker_transaction_v3"]["required"]) == {
        "transaction_id",
        "nonce",
        "lock_identity",
        "input_manifest_sha256",
        "gate_sha256",
        "test_sha256",
        "schema_digest",
    }
    assert set(schema["$defs"]["marker_predecessor_v2_v3"]["required"]) == {
        "receipt_path",
        "receipt_sha256",
        "preserved",
        "current_revoked",
    }
    assert "nested_closed" not in json.dumps(schema)
    assert (
        m.canonical_sha(schema)
        == contract["h_b_v3_closed_contract"]["schema_digest_contract"][
            "marker_schema_sha256"
        ]
    )


@pytest.mark.parametrize(
    "files,control,expected",
    [
        (
            {
                "intent": False,
                "evidence": False,
                "ledger_prepared": False,
                "cycle_prepared": False,
                "audit_ready": False,
                "marker": False,
            },
            {},
            "S0_ALLOCATED",
        ),
        (
            {
                "intent": True,
                "evidence": False,
                "ledger_prepared": False,
                "cycle_prepared": False,
                "audit_ready": False,
                "marker": False,
            },
            {},
            "S1_INTENT",
        ),
        (
            {
                "intent": True,
                "evidence": True,
                "ledger_prepared": False,
                "cycle_prepared": False,
                "audit_ready": False,
                "marker": False,
            },
            {},
            "S2_EVIDENCE",
        ),
        (
            {
                "intent": True,
                "evidence": True,
                "ledger_prepared": True,
                "cycle_prepared": False,
                "audit_ready": False,
                "marker": False,
            },
            {"ledger": "prepared"},
            "S3_LEDGER_ONLY",
        ),
        (
            {
                "intent": True,
                "evidence": True,
                "ledger_prepared": True,
                "cycle_prepared": True,
                "audit_ready": False,
                "marker": False,
            },
            {"ledger": "prepared", "cycle": "prepared"},
            "S4_BOTH_PREPARED",
        ),
        (
            {
                "intent": True,
                "evidence": True,
                "ledger_prepared": True,
                "cycle_prepared": True,
                "audit_ready": True,
                "marker": False,
            },
            {"ledger": "prepared", "cycle": "prepared"},
            "S5_AUDIT_READY",
        ),
        (
            {
                "intent": True,
                "evidence": True,
                "ledger_prepared": True,
                "cycle_prepared": True,
                "audit_ready": True,
                "marker": True,
            },
            {"ledger": "prepared", "cycle": "prepared"},
            "S6_COMMITTED",
        ),
    ],
)
def test_partial_cas_state_classification(
    files: dict, control: dict, expected: str
) -> None:
    assert m.classify_transaction(files, control) == expected


def test_impossible_partial_state_is_sx() -> None:
    assert (
        m.classify_transaction(
            {
                "intent": False,
                "evidence": True,
                "ledger_prepared": False,
                "cycle_prepared": False,
                "audit_ready": False,
                "marker": False,
            },
            {},
        )
        == "SX_INCONSISTENT"
    )


def test_no_replace_is_idempotent_exact_but_rejects_collision(tmp_path: Path) -> None:
    path = tmp_path / "out"
    assert m.no_replace_write(path, b"x") == _sha(b"x")
    assert m.no_replace_write(path, b"x") == _sha(b"x")
    with pytest.raises(m.GateError):
        m.no_replace_write(path, b"y")


def test_exact_cas_rejects_preimage_drift(tmp_path: Path) -> None:
    path = tmp_path / "c"
    path.write_bytes(b"a")
    with pytest.raises(m.GateError) as error:
        m.exact_cas(path, b"wrong", b"b")
    assert error.value.code == "control_plane_cas_invalid"
    assert path.read_bytes() == b"a"


def test_exclusive_lock_denies_competitor(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    with m.exclusive_lock(path):
        with pytest.raises(m.GateError) as error:
            with m.exclusive_lock(path):
                pass
    assert error.value.code == "lock_or_writer_race"


def test_sandbox_transaction_requires_marked_non_repository_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "spec.json").write_text("{}")
    with pytest.raises(m.GateError) as error:
        m.sandbox_transaction(tmp_path, "spec.json")
    assert error.value.code == "publication_transaction_failed"


def test_legacy_fan_in_is_permanently_non_authorizing(tmp_path: Path) -> None:
    result = _run(tmp_path, "--phase", "fan-in")
    output = json.loads(result.stdout)
    assert result.returncode == 1
    assert output["findings"][0]["code"] == "stale_h_b_generation"
    assert output["final_qa_eligible"] is False
    assert output["lane_completion_allowed"] is False
    assert output["commit_allowed"] is False


def test_dispatch_compatibility_is_non_completing(tmp_path: Path) -> None:
    lane = tmp_path / "lane.json"
    pipe = tmp_path / "pipe.json"
    peer = tmp_path / "peer.json"
    lane.write_text(
        json.dumps(
            {
                "core_dev_dispatch_allowed": True,
                "requirement": {"lane_b_authored_paths": ["x"]},
            }
        )
    )
    pipe.write_text(json.dumps({"pipelines": {"pipeline-0": {"dependencies": []}}}))
    peer.write_text(
        json.dumps(
            {"development_approach": {"files_to_modify": ["y"], "files_to_create": []}}
        )
    )
    result = _run(
        tmp_path,
        "--phase",
        "dispatch",
        "--lane-context",
        "lane.json",
        "--pipeline-contract",
        "pipe.json",
        "--peer-context",
        "peer.json",
    )
    output = json.loads(result.stdout)
    assert result.returncode == 0 and output["status"] == "pass"
    assert (
        output["lane_completion_allowed"] is False and output["commit_allowed"] is False
    )


def test_missing_strict_inputs_have_deterministic_codes(tmp_path: Path) -> None:
    cases = [
        (("--phase", "verify-h-b-v3-provider-set"), "h_b_v3_attempt_identity_invalid"),
        (("--phase", "verify-h-b-v3-commit"), "h_b_v3_not_committed"),
        (("--phase", "produce-fan-in-v2"), "invalid_envelope"),
        (("--phase", "consume-fan-in-v2"), "invalid_envelope"),
        (("--phase", "sandbox-transaction"), "publication_transaction_failed"),
    ]
    for args, code in cases:
        output = json.loads(_run(tmp_path, *args).stdout)
        assert output["findings"][0]["code"] == code
        assert output["authorizes"] == [] and output["final_qa_eligible"] is False


def test_nf_and_hb3_code_denominators_are_closed() -> None:
    assert len(m.HB3_CODES) == 20 and len(set(m.HB3_CODES)) == 20
    assert len(m.NF_CODES) == 32 and len(set(m.NF_CODES)) == 32
    assert m.DIRECT_PROVIDERS == (
        "H_B_CURRENT",
        "H_POL_AUTH",
        "H_BIND_EFFECTIVE",
        "LANE_LEASE_TERMINAL",
    )
    assert m.TERMINAL_PREREQUISITES == ("SCHEMA", "R1", "RS", "F", "L", "SU", "DOC")
    assert len(m.MATRIX_IDS) == 13


def test_cleanup_black_box_executes_production_ab_and_seven_negatives() -> None:
    first = m.run_cleanup_black_box(ROOT)
    second = m.run_cleanup_black_box(ROOT)
    assert first == second
    assert first["positive_case"] == {
        "only_A_finalized": True,
        "B_preserved": True,
    }
    assert first["production_executables"] == [
        "hooks/stop-workflow-coordinator.py",
        "hooks/stop-cleanup-allowlist.sh",
        "scripts/session-resources.py",
    ]
    assert first["negative_cases"] == {
        name: "pass_no_mutation_or_signal"
        for name in (
            "expired_lease",
            "wrong_repo_identity",
            "wrong_HEAD",
            "wrong_nonce_owner_session",
            "timeout_nonzero_invalid",
            "receipt_mismatch",
            "PID_start_mismatch",
        )
    }
    assert m.SHA_RE.fullmatch(first["result_sha256"])


def test_live_git_process_and_writable_fd_census_rejects_forged_zero(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Fixture"], check=True
    )
    (root / "hooks").mkdir()
    (root / "hooks/stop-workflow-coordinator.py").write_text("fixture\n")
    (root / "bound.json").write_text("bound\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    envelope = {
        "gate": {
            "path": "bound.json",
            "sha256": "a" * 64,
            "producer_role": "updatedInput",
            "consumer_role": "same-spec parent",
        }
    }
    clean = m.live_ownership_census(root, envelope)
    assert clean["git_snapshot_sha256"] == _sha(
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v2",
                "--branch",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            check=True,
        ).stdout
    )
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,sys,time; os.chdir(sys.argv[1]); f=open('bound.json','ab'); "
            "print('ready',flush=True); time.sleep(30)",
            str(root),
        ],
        text=True,
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout and holder.stdout.readline().strip() == "ready"
        live = m.live_ownership_census(root, envelope)
        assert live["bound_writable_handle_count"] >= 1
        assert live["bound_provider_process_count"] >= 1
        forged = copy.deepcopy(live)
        forged["bound_writable_handle_count"] = 0
        forged["bound_provider_process_count"] = 0
        with pytest.raises(m.GateError) as error:
            if forged != m.live_ownership_census(root, envelope):
                m._deny(
                    "active_handle_or_process",
                    "live process/open-FD census is nonzero or forged",
                )
        assert error.value.code == "active_handle_or_process"
    finally:
        holder.kill()
        holder.wait(timeout=5)


def _copy_with_mode(source: Path, target: Path, mode: str | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    target.chmod(int(mode, 8) if mode else stat.S_IMODE(source.stat().st_mode))


def _full_hb3_fixture(tmp_path: Path) -> tuple[Path, dict, str]:
    contract = _contract()
    contract_rel = (
        "docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json"
    )
    _copy_with_mode(CONTRACT, tmp_path / contract_rel, "0644")
    for reference in contract["h_b_v3_closed_contract"]["manifest"]["rows"]:
        _copy_with_mode(
            ROOT / reference["path"], tmp_path / reference["path"], reference["mode"]
        )
    _copy_with_mode(ROOT / m.V2_READINESS, tmp_path / m.V2_READINESS, "0444")
    _copy_with_mode(ROOT / m.V2_RECEIPT, tmp_path / m.V2_RECEIPT, "0444")

    attempt = "a000001"
    paths = m.derive_paths(contract, "GATE_REPAIR_HB3", attempt)
    dynamic = []
    realized = []
    for reference in contract["h_b_v3_closed_contract"]["manifest"]["rows"]:
        path = tmp_path / reference["path"]
        row = {
            "ordinal": reference["ordinal"],
            "path": reference["path"],
            "role": reference["role"],
            "mode": f"0{stat.S_IMODE(path.stat().st_mode):03o}",
            "bytes": path.stat().st_size,
            "sha256": _sha(path.read_bytes()),
            "hash_authority": reference["hash_authority"],
        }
        realized.append(row)
        if reference["hash_authority"] == "selected_repair_dev_and_qa_exact":
            dynamic.append(
                {key: row[key] for key in ("path", "mode", "bytes", "sha256")}
            )
    dev = {
        "$schema": "dev-report.v1",
        "task_id": "fixture-hb3-repair",
        "request_id": "fixture-hb3-repair",
        "lane_id": "LANE-B",
        "pipeline_id": "pipeline-0",
        "attempt_id": attempt,
        "status": "completed",
        "files_modified": [
            "scripts/laneb-integration-gate.py",
            "hooks/tests/test_laneb_integration_gate.py",
        ],
        "files_created": [paths["dev_report"]],
        "source_test_rows": dynamic,
        "source_test_rows_sha256": m.canonical_sha(dynamic),
    }
    dev_path = tmp_path / paths["dev_report"]
    dev_path.parent.mkdir(parents=True, exist_ok=True)
    dev_path.write_bytes(_canonical(dev))
    qa = {
        "$schema": "qa-report.v1",
        "task_id": "fixture-hb3-repair",
        "lane_id": "LANE-B",
        "pipeline_id": "pipeline-0",
        "attempt_id": attempt,
        "verdict": "pass",
        "independent": True,
        "dev_report_sha256": _sha(dev_path.read_bytes()),
        "gate_sha256": next(
            row["sha256"]
            for row in realized
            if row["path"] == "scripts/laneb-integration-gate.py"
        ),
        "test_sha256": next(
            row["sha256"]
            for row in realized
            if row["path"] == "hooks/tests/test_laneb_integration_gate.py"
        ),
        "realized_manifest_sha256": m.canonical_sha(realized),
        "verification_matrix_sha256": "e" * 64,
    }
    qa_path = tmp_path / paths["qa_report"]
    qa_path.write_bytes(_canonical(qa))

    allocation = _event(
        contract,
        sequence=1,
        kind="GATE_REPAIR_HB3",
        attempt=attempt,
        event_type="ALLOCATED",
        outcome="none",
        previous=None,
    )
    started = _event(
        contract,
        sequence=2,
        kind="GATE_REPAIR_HB3",
        attempt=attempt,
        event_type="STARTED",
        outcome="pending",
        previous=_sha(_canonical(allocation)),
    )
    registry = tmp_path / m.REGISTRY_DEFAULT
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_bytes(_canonical(allocation) + b"\n" + _canonical(started) + b"\n")

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Fixture"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    return tmp_path, contract, attempt


def test_full_production_shaped_hb3_provider_set_positive(tmp_path: Path) -> None:
    root, _contract_value, attempt = _full_hb3_fixture(tmp_path)
    result = m.verify_hb3_provider_set(
        root,
        contract_path="docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json",
        registry_path=m.REGISTRY_DEFAULT,
        attempt_id=attempt,
    )
    assert result["record_type"] == "h_b_v3_canonical_verifier_result"
    assert result["decision"] == {
        "status": "pass",
        "provider_set_valid": True,
        "authority": False,
        "authorizes": [],
    }
    assert len(result["manifest"]["rows"]) == 16
    assert len(result["negative_matrix"]) == 20
    m.validate_integrity(result, code="h_b_v3_verifier_invalid")


def _write_integrity(value: dict) -> None:
    value["integrity"] = {
        "canonical_payload_sha256": "0" * 64,
        "canonicalization": "UTF-8 sorted-key compact JSON, excluding only this canonical_payload_sha256 field; no Unicode normalization",
    }
    value["integrity"]["canonical_payload_sha256"] = m._payload_digest(value)


def _artifact_ref(root: Path, path: str, schema_id: str) -> dict:
    item = root / path
    info = item.stat()
    return {
        "path": path,
        "sha256": _sha(item.read_bytes()),
        "bytes": info.st_size,
        "mode": f"0{stat.S_IMODE(info.st_mode):03o}",
        "schema_id": schema_id,
    }


def _bound_ref(
    root: Path,
    path: str,
    *,
    producer: str = "provider",
    consumer: str = "same-spec parent",
) -> dict:
    item = root / path
    info = item.stat()
    return {
        "path": path,
        "sha256": _sha(item.read_bytes()),
        "bytes": info.st_size,
        "mode": f"0{stat.S_IMODE(info.st_mode):03o}",
        "device": info.st_dev,
        "inode": info.st_ino,
        "schema_id": "nf.fixture.v1",
        "schema_version": 1,
        "semantic_identity": {"path": path},
        "producer_role": producer,
        "consumer_role": consumer,
        "selected_attempt": "a000001",
        "independent_qa_binding": "nf32-repair3",
    }


def _install_hb3_commit_fixture(root: Path, contract: dict, attempt: str) -> str:
    paths = m.derive_paths(contract, "GATE_REPAIR_HB3", attempt)
    verifier = m.verify_hb3_provider_set(
        root,
        contract_path="docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json",
        registry_path=m.REGISTRY_DEFAULT,
        attempt_id=attempt,
    )
    verifier_path = root / paths["verifier_result"]
    verifier_path.parent.mkdir(parents=True, exist_ok=True)
    verifier_path.write_bytes(_canonical(verifier))
    identity = verifier["identity"]
    attempt_value = verifier["attempt"]
    selected_dev = verifier["selected_dev"]
    selected_qa = verifier["selected_qa"]
    source_manifest = verifier["manifest"]
    predecessor = verifier["predecessor_v2"]
    freshness = _fresh(snapshot_id="9" * 64)
    transaction = {
        "transaction_id": f"tx-GATE_REPAIR_HB3-{attempt}",
        "nonce": hashlib.sha256(f"GATE_REPAIR_HB3:{attempt}".encode()).hexdigest(),
        "attempt_id": attempt,
        "sequence": 1,
        "registry_event_sha256": attempt_value["registry_allocation_event_sha256"],
        "input_manifest_sha256": source_manifest["realized_rows_sha256"],
        "lock_identity": "same-spec-parent-reconciliation-lock",
    }
    verifier_ref = {
        "artifact": _artifact_ref(
            root, paths["verifier_result"], "h_b_v3_canonical_verifier_result"
        ),
        "phase": "verify-h-b-v3-provider-set",
        "gate_binary_sha256": verifier["gate_binary"]["sha256"],
        "decision": "pass",
        "result_digest": verifier["integrity"]["canonical_payload_sha256"],
    }
    control_cycle = "fixture/cycle.json"
    control_ledger = "fixture/ledger.json"
    (root / "fixture").mkdir()
    (root / control_cycle).write_bytes(
        _canonical({"status": "terminal", "cycle_id": 1})
    )
    (root / control_ledger).write_bytes(
        _canonical({"status": "terminal", "writers": []})
    )
    control_prestate = {
        "cycle": _artifact_ref(root, control_cycle, "cycle.fixture.v1"),
        "ledger": _artifact_ref(root, control_ledger, "ledger.fixture.v1"),
        "lock_identity": "same-spec-parent-reconciliation-lock",
        "prestate_manifest_sha256": m.canonical_sha([control_cycle, control_ledger]),
    }
    readiness = {
        "schema_version": 3,
        "record_type": "h_b_core_pol_provider_publication_readiness.v3",
        "record_status": "ready_non_authorizing",
        "identity": identity,
        "attempt": attempt_value,
        "predecessor_v2": predecessor,
        "selected_dev": selected_dev,
        "selected_qa": selected_qa,
        "source_test_manifest": source_manifest,
        "verifier": verifier_ref,
        "control_prestate": control_prestate,
        "freshness": freshness,
        "transaction": transaction,
        "expected_receipt_path": paths["receipt"],
        "expected_commit_marker_path": paths["commit_marker"],
        "decision": {
            "H_B_v3_current": False,
            "POL_start_allowed": False,
            "BIND_start_allowed": False,
            "fan_in_allowed": False,
            "lane_completion_allowed": False,
            "spec_completion_allowed": False,
            "close_allowed": False,
            "commit_allowed": False,
            "authorizes": [],
        },
    }
    _write_integrity(readiness)
    readiness_path = root / paths["readiness"]
    readiness_path.write_bytes(_canonical(readiness))
    receipt = {
        "schema_version": 3,
        "record_type": "h_b_core_pol_provider_publication_receipt.v3",
        "record_status": "published_non_authorizing_until_external_marker",
        "identity": identity,
        "attempt": attempt_value,
        "readiness": _artifact_ref(
            root, paths["readiness"], "h_b_core_pol_provider_publication_readiness.v3"
        ),
        "predecessor_v2": predecessor,
        "provider_pair": {"dev": selected_dev, "qa": selected_qa},
        "source_test_manifest": source_manifest,
        "verifier": verifier_ref,
        "transaction": transaction,
        "publication_effect": {
            "H_B_v3_current": False,
            "POL_start_allowed": False,
            "downstream_allowed": False,
            "completion_allowed": False,
            "close_allowed": False,
            "commit_allowed": False,
            "authorizes": [],
        },
    }
    _write_integrity(receipt)
    receipt_path = root / paths["receipt"]
    receipt_path.write_bytes(_canonical(receipt))
    marker = {
        "schema_version": 3,
        "record_type": "h_b_core_pol_provider_publication_commit_marker.v3",
        "record_status": "committed_current_h_b_provider",
        "identity": identity,
        "attempt": attempt_value,
        "transaction": {
            "transaction_id": transaction["transaction_id"],
            "nonce": transaction["nonce"],
            "lock_identity": transaction["lock_identity"],
            "input_manifest_sha256": transaction["input_manifest_sha256"],
            "gate_sha256": verifier["gate_binary"]["sha256"],
            "test_sha256": selected_qa["test_sha256"],
            "schema_digest": contract["h_b_v3_closed_contract"][
                "external_commit_marker"
            ]["schema_sha256"],
        },
        "predecessor_v2": {
            "receipt_path": m.V2_RECEIPT,
            "receipt_sha256": m.V2_RECEIPT_SHA,
            "preserved": True,
            "current_revoked": True,
        },
        "selected_provider": {
            "readiness_path": paths["readiness"],
            "readiness_sha256": _sha(readiness_path.read_bytes()),
            "receipt_path": paths["receipt"],
            "receipt_sha256": _sha(receipt_path.read_bytes()),
            "verifier_path": paths["verifier_result"],
            "verifier_sha256": _sha(verifier_path.read_bytes()),
            "dev_path": selected_dev["artifact"]["path"],
            "dev_sha256": selected_dev["artifact"]["sha256"],
            "qa_path": selected_qa["artifact"]["path"],
            "qa_sha256": selected_qa["artifact"]["sha256"],
            "source_test_manifest_sha256": source_manifest["realized_rows_sha256"],
        },
        "control_plane": {
            "cycle_path": control_cycle,
            "cycle_pre_sha256": control_prestate["cycle"]["sha256"],
            "cycle_post_sha256": "1" * 64,
            "ledger_path": control_ledger,
            "ledger_pre_sha256": control_prestate["ledger"]["sha256"],
            "ledger_post_sha256": "2" * 64,
            "permitted_delta_sha256": "3" * 64,
            "expected_marker_path": paths["commit_marker"],
        },
        "audit": {
            "audit_path": paths["step_05_audit_result"],
            "intent_record_sha256": "4" * 64,
            "terminal_record_sha256": "5" * 64,
            "previous_record_sha256": "6" * 64,
        },
        "installation_contract": {
            "no_replace": True,
            "file_fsync": True,
            "directory_fsync": True,
            "marker_installed_last_under_lock": True,
            "lock_released_after_directory_fsync": True,
            "full_marker_sha256_external": True,
        },
        "decision": {
            "H_B_v3_current": True,
            "POL_start_allowed": True,
            "allowed_consumer": "fresh pipeline-5/LANE-POL attempt bound to this marker path+external SHA",
            "BIND_start_allowed": False,
            "fan_in_allowed": False,
            "lane_completion_allowed": False,
            "spec_completion_allowed": False,
            "close_allowed": False,
            "commit_allowed": False,
            "authorizes": ["fresh_POL_attempt_start_gate_only"],
        },
    }
    marker["integrity"] = {
        "canonical_payload_sha256": "0" * 64,
        "canonicalization": "UTF-8 sorted-key compact JSON excluding only canonical_payload_sha256; marker file SHA is external",
    }
    marker["integrity"]["canonical_payload_sha256"] = m._payload_digest(marker)
    marker_path = root / paths["commit_marker"]
    marker_path.write_bytes(_canonical(marker))
    binding = {
        "schema_version": 3,
        "record_type": "h_b_current_provider_binding.v3",
        "attempt_kind": "GATE_REPAIR_HB3",
        "attempt_id": attempt,
        "readiness": _artifact_ref(
            root, paths["readiness"], "h_b_core_pol_provider_publication_readiness.v3"
        ),
        "receipt": _artifact_ref(
            root, paths["receipt"], "h_b_core_pol_provider_publication_receipt.v3"
        ),
        "selected_dev": _artifact_ref(
            root, selected_dev["artifact"]["path"], "dev-report.v1"
        ),
        "selected_qa": _artifact_ref(
            root, selected_qa["artifact"]["path"], "qa-report.v1"
        ),
        "external_commit_marker": {
            **_artifact_ref(
                root,
                paths["commit_marker"],
                "h_b_core_pol_provider_publication_commit_marker.v3",
            ),
            "sha256_external": _sha(marker_path.read_bytes()),
        },
    }
    binding["external_commit_marker"].pop("sha256")
    binding["integrity"] = {
        "canonical_payload_sha256": "0" * 64,
        "canonicalization": "UTF-8 sorted-key compact JSON; excludes only canonical_payload_sha256",
    }
    binding["integrity"]["canonical_payload_sha256"] = m._payload_digest(binding)
    binding_path = "fixture/h-b-current-binding.json"
    (root / binding_path).write_bytes(_canonical(binding))
    return binding_path


def _nf_write_envelope(root: Path, path: str, value: dict) -> None:
    value["integrity"]["canonical_payload_sha256"] = m._payload_digest(value)
    (root / path).write_bytes(_canonical(value))


def _full_fanin_fixture(root: Path) -> tuple[dict, str, str]:
    root, contract, attempt = _full_hb3_fixture(root)
    binding_path = _install_hb3_commit_fixture(root, contract, attempt)
    for relative in (
        "hooks/stop-workflow-coordinator.py",
        "hooks/stop-cleanup-allowlist.sh",
        "scripts/session-resources.py",
        "hooks/lib/session_resources.py",
        "hooks/lib/allowlist.py",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_with_mode(ROOT / relative, target)
    evidence_path = "fixture/nf-evidence.json"
    envelope_path = "fixture/nf-envelope.json"
    (root / evidence_path).write_bytes(_canonical({"status": "pass"}))
    (root / envelope_path).write_bytes(b"{}")
    binding = json.loads((root / binding_path).read_text())
    evidence = _bound_ref(root, evidence_path)

    def provider(task: str, consumed: dict, **identity: object) -> dict:
        return {
            "task_id": task,
            "status": "pass",
            "attempt_id": "a000001",
            "dev": evidence,
            "qa": evidence,
            "handoff": evidence,
            "consumed": consumed,
            **identity,
        }

    providers = {
        "H_B_CURRENT": {
            "binding": binding,
            "binding_artifact": _bound_ref(root, binding_path),
        },
        "H_POL_AUTH": provider(
            "20260810-lane-pol-redesign",
            {"H_B_CURRENT": "1" * 64},
            consumed_h_b_current={
                "generation": 3,
                "marker_path": binding["external_commit_marker"]["path"],
                "marker_sha256_external": binding["external_commit_marker"][
                    "sha256_external"
                ],
            },
        ),
        "H_BIND_EFFECTIVE": provider(
            "20260809-102007-7",
            {"H_B_CURRENT": "1" * 64, "H_POL_AUTH": "2" * 64},
        ),
        "LANE_LEASE_TERMINAL": provider(
            "20260809-102007-9", {"H_BIND_EFFECTIVE": "3" * 64}
        ),
    }
    prerequisites = {
        name: {
            "status": "pass",
            "dev": evidence,
            "qa": evidence,
            "handoff": evidence,
            "lineage_sha256": _sha(name.encode()),
        }
        for name in m.TERMINAL_PREREQUISITES
    }
    matrix = [
        {
            "id": name,
            "status": "pass",
            "providers": ["nf-fixture"],
            "evidence": [evidence],
            "result_sha256": _sha(name.encode()),
        }
        for name in m.MATRIX_IDS
    ]
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "-C", str(root), "branch", "--show-current"], text=True
    ).strip()
    marker_sha = binding["external_commit_marker"]["sha256_external"]
    registry_path = root / m.REGISTRY_DEFAULT
    registry_rows = [
        json.loads(line) for line in registry_path.read_text().splitlines()
    ]
    previous = _sha(_canonical(registry_rows[-1]))
    allocation = _event(
        contract,
        sequence=len(registry_rows) + 1,
        kind="FINAL_FAN_IN",
        attempt="a000001",
        event_type="ALLOCATED",
        outcome="none",
        previous=previous,
    )
    registry_rows.append(allocation)
    registry_path.write_bytes(
        b"".join(_canonical(row) + b"\n" for row in registry_rows)
    )
    allocation_raw = _canonical(allocation)
    envelope = {
        "schema_version": 2,
        "record_type": "laneb_fan_in_envelope.v2",
        "record_status": "immutable_pre_final_qa_fan_in",
        "identity": {
            "session_id": m.SESSION_ID,
            "spec_id": m.SPEC_ID,
            "cycle_id": m.CYCLE_ID,
            "task_id": "nf32-repair3",
            "lane_id": m.LANE_ID,
            "pipeline_id": m.PIPELINE_ID,
            "active_root_realpath": str(root.resolve()),
            "git_head": head,
            "git_branch": branch,
        },
        "freshness": _fresh(),
        "transaction": {
            "id": "nf32-transaction",
            "transaction_id": allocation["transaction_id"],
            "nonce": allocation["nonce"],
            "attempt_kind": "FINAL_FAN_IN",
            "attempt_id": "a000001",
            "registry_path": m.REGISTRY_DEFAULT,
            "registry_event_sha256": _sha(allocation_raw),
            "external_commit_marker_sha256": marker_sha,
        },
        "gate": _bound_ref(
            root, "scripts/laneb-integration-gate.py", producer="updatedInput"
        ),
        "providers": providers,
        "terminal_prerequisites": prerequisites,
        "control_plane_prestate": {
            "status": "nf-fixture",
            "cycle_semantics": {
                "session_id": m.SESSION_ID,
                "spec_id": m.SPEC_ID,
                "cycle_id": m.CYCLE_ID,
                "status": "terminal",
            },
            "ledger_semantics": {"status": "terminal", "active_writer_count": 0},
        },
        "effective_surface": {"status": "nf-fixture"},
        "ownership_snapshot": {},
        "matrix_results": matrix,
        "cleanup_black_box": {},
        "decision": {
            "fan_in_status": "pass",
            "H_B_FANIN_passed": True,
            "final_qa_eligible": True,
            **m.NONCLAIMS,
            "authorizes": [
                "independent_final_LANE_B_QA_dispatch_only_after_external_commit_marker"
            ],
        },
        "audit_binding": {"status": "nf-fixture"},
        "integrity": {
            "canonical_payload_sha256": "0" * 64,
            "canonicalization": "UTF-8 sorted-key compact JSON, excluding canonical_payload_sha256",
        },
    }
    built = m.build_runtime_attestations(root, envelope)
    now = dt.datetime.now(dt.timezone.utc)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    built["freshness"] = {
        "snapshot_id": "a" * 64,
        "observed_at": stamp(now),
        "generated_at": stamp(now),
        "expires_at": stamp(now + dt.timedelta(seconds=15)),
        "window_seconds": 15,
        "monotonic_start_ns": time.monotonic_ns(),
        "monotonic_end_ns": time.monotonic_ns(),
    }
    _nf_write_envelope(root, envelope_path, built)
    return contract, binding_path, envelope_path


def _replace_artifact(root: Path, envelope: dict, ref: dict, payload: bytes) -> None:
    path = root / ref["path"]
    path.write_bytes(payload)
    info = path.stat()
    ref.update(
        {
            "sha256": _sha(payload),
            "bytes": info.st_size,
            "device": info.st_dev,
            "inode": info.st_ino,
        }
    )


def _apply_nf_mutation(
    root: Path,
    envelope_path: str,
    immutable_baseline: dict,
    case_id: str,
) -> None:
    envelope = copy.deepcopy(immutable_baseline)
    providers = envelope["providers"]
    prereqs = envelope["terminal_prerequisites"]
    if case_id == "NF-01":
        providers["H_POL_AUTH"]["status"] = "waiting"
    elif case_id == "NF-02":
        providers["H_B_CURRENT"]["binding"]["schema_version"] = 2
    elif case_id == "NF-03":
        binding = providers["H_B_CURRENT"]["binding"]
        marker_path = binding["external_commit_marker"]["path"]
        marker = json.loads((root / marker_path).read_text())
        marker["selected_provider"]["source_test_manifest_sha256"] = "0" * 64
        marker["integrity"]["canonical_payload_sha256"] = m._payload_digest(marker)
        marker_payload = _canonical(marker)
        (root / marker_path).write_bytes(marker_payload)
        marker_info = (root / marker_path).stat()
        binding["external_commit_marker"].update(
            {
                "sha256_external": _sha(marker_payload),
                "bytes": marker_info.st_size,
            }
        )
        binding["integrity"]["canonical_payload_sha256"] = m._payload_digest(binding)
        binding_path = providers["H_B_CURRENT"]["binding_artifact"]["path"]
        binding_payload = _canonical(binding)
        _replace_artifact(
            root,
            envelope,
            providers["H_B_CURRENT"]["binding_artifact"],
            binding_payload,
        )
    elif case_id == "NF-04":
        providers["H_POL_AUTH"]["consumed_h_b_current"]["generation"] = 2
    elif case_id == "NF-05":
        providers["H_POL_AUTH"]["qa"] = {}
    elif case_id == "NF-06":
        providers["H_POL_AUTH"]["consumed"]["H_B_CURRENT"] = "wrong"
    elif case_id == "NF-07":
        providers["H_POL_AUTH"]["task_id"] = "historical-pol-iteration-5"
    elif case_id == "NF-08":
        providers["H_BIND_EFFECTIVE"]["consumed"].pop("H_POL_AUTH")
    elif case_id == "NF-09":
        providers["LANE_LEASE_TERMINAL"]["consumed"] = {}
    elif case_id == "NF-10":
        envelope["cleanup_black_box"]["mock_free"] = False
    elif case_id == "NF-11":
        envelope["cleanup_black_box"]["positive_case"]["B_preserved"] = False
    elif case_id == "NF-12":
        envelope["control_plane_prestate"]["cycle_semantics"]["cycle_id"] = 2
    elif case_id == "NF-13":
        envelope["control_plane_prestate"]["ledger_semantics"][
            "active_writer_count"
        ] = 1
    elif case_id == "NF-14":
        envelope["ownership_snapshot"]["overlapping_claim_count"] = 1
    elif case_id == "NF-15":
        envelope["ownership_snapshot"]["bound_writable_handle_count"] = 1
    elif case_id == "NF-16":
        envelope["effective_surface"] = {}
    elif case_id == "NF-17":
        envelope["matrix_results"][0]["evidence"] = []
    elif case_id == "NF-18":
        envelope["matrix_results"].pop()
    elif case_id == "NF-19":
        prereqs["SCHEMA"]["status"] = "pending"
    elif case_id == "NF-20":
        prereqs["SU"]["status"] = "pending"
    elif case_id == "NF-21":
        envelope["record_status"] = "unknown"
    elif case_id == "NF-22":
        envelope["freshness"]["expires_at"] = "2000-01-01T00:00:00Z"
    elif case_id == "NF-23":
        pass
    elif case_id == "NF-24":
        envelope["transaction"]["lock_state"] = "lost"
    elif case_id == "NF-25":
        envelope["identity"]["git_head"] = "0" * 40
    elif case_id == "NF-26":
        envelope["transaction"]["publication_collision"] = True
    elif case_id == "NF-27":
        registry_path = root / envelope["transaction"]["registry_path"]
        rows = [json.loads(line) for line in registry_path.read_text().splitlines()]
        replay = _event(
            _contract(),
            sequence=len(rows) + 1,
            kind="POL_EXTERNAL",
            attempt="a000001",
            event_type="ALLOCATED",
            outcome="none",
            previous=_sha(_canonical(rows[-1])),
        )
        replay["nonce"] = envelope["transaction"]["nonce"]
        payload = copy.deepcopy(replay)
        del payload["integrity"]["event_payload_sha256"]
        replay["integrity"]["event_payload_sha256"] = m.canonical_sha(payload)
        rows.append(replay)
        registry_path.write_bytes(b"".join(_canonical(row) + b"\n" for row in rows))
    elif case_id == "NF-28":
        envelope["audit_binding"] = {}
    elif case_id == "NF-29":
        envelope["control_plane_prestate"] = {}
    elif case_id == "NF-30":
        envelope["transaction"]["external_commit_marker_sha256"] = "0" * 64
    elif case_id == "NF-31":
        envelope["decision"]["lane_completion_allowed"] = True
    elif case_id == "NF-32":
        envelope["ownership_snapshot"]["registry_roles"] = []
    _nf_write_envelope(root, envelope_path, envelope)


def _nf_fixture_factory() -> dict:
    outer = Path(tempfile.mkdtemp(prefix="laneb-nf32-diagnostic-", dir="/var/tmp"))
    root = outer / "project"
    root.mkdir()
    _contract_value, binding_path, envelope_path = _full_fanin_fixture(root)
    immutable_baseline = json.loads((root / envelope_path).read_bytes())
    mutable_paths = (
        immutable_baseline["providers"]["H_B_CURRENT"]["binding_artifact"]["path"],
        immutable_baseline["providers"]["H_B_CURRENT"]["binding"][
            "external_commit_marker"
        ]["path"],
        immutable_baseline["transaction"]["registry_path"],
    )
    mutable_baseline = {path: (root / path).read_bytes() for path in mutable_paths}
    original_validate_envelope = m.validate_envelope

    def reset() -> None:
        m.validate_envelope = original_validate_envelope
        for path, payload in mutable_baseline.items():
            (root / path).write_bytes(payload)
        baseline = copy.deepcopy(immutable_baseline)
        now = dt.datetime.now(dt.timezone.utc)
        stamp = lambda value: value.isoformat().replace("+00:00", "Z")
        baseline["freshness"] = {
            "snapshot_id": "a" * 64,
            "observed_at": stamp(now),
            "generated_at": stamp(now),
            "expires_at": stamp(now + dt.timedelta(seconds=15)),
            "window_seconds": 15,
            "monotonic_start_ns": time.monotonic_ns(),
            "monotonic_end_ns": time.monotonic_ns(),
        }
        _nf_write_envelope(root, envelope_path, baseline)

    def mutate(case_id: str) -> None:
        fresh_baseline = json.loads((root / envelope_path).read_text())
        _apply_nf_mutation(root, envelope_path, fresh_baseline, case_id)
        if case_id == "NF-23":
            captured = threading.Event()
            written = threading.Event()

            def writer() -> None:
                assert captured.wait(timeout=5)
                path = root / envelope_path
                with path.open("ab") as handle:
                    handle.write(b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                written.set()

            def validate_then_drift(*args: object, **kwargs: object) -> object:
                result = original_validate_envelope(*args, **kwargs)
                thread = threading.Thread(target=writer)
                thread.start()
                captured.set()
                assert written.wait(timeout=5)
                thread.join(timeout=5)
                return result

            m.validate_envelope = validate_then_drift

    return {
        "root": root,
        "contract_path": "docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json",
        "binding_path": binding_path,
        "envelope_path": envelope_path,
        "reset": reset,
        "mutate": mutate,
        "cleanup": lambda: __import__("shutil").rmtree(outer, ignore_errors=True),
    }


def test_nf_01_through_nf_32_mutate_full_fixture_and_real_validators() -> None:
    rows = m.exercise_nf32_matrix(_contract(), _nf_fixture_factory)
    assert [row["ordinal"] for row in rows] == list(range(1, 33))
    assert [row["id"] for row in rows] == [f"NF-{index:02d}" for index in range(1, 33)]
    assert [row["expected_code"] for row in rows] == list(m.NF_CODES)
    assert rows[29]["observations"] == [
        {
            "stage": "consumer",
            "entrypoint": "consume_envelope",
            "expected_code": "uncommitted_receipt",
            "actual_code": "uncommitted_receipt",
        }
    ]
    assert all(len(row["observations"]) == 2 for row in rows if row["id"] != "NF-30")
    mismatches = [
        {
            "id": row["id"],
            "expected_code": row["expected_code"],
            "observations": row["observations"],
        }
        for row in rows
        if row["status"] != "pass"
    ]
    print(json.dumps({"mismatches": mismatches, "rows": rows}, sort_keys=True))
    assert not mismatches, json.dumps(mismatches, sort_keys=True)


def test_nf_03_04_23_27_each_baseline_mutation_reset_real_entrypoints() -> None:
    fixture = _nf_fixture_factory()
    root = fixture["root"]
    contract_path = fixture["contract_path"]
    envelope_path = fixture["envelope_path"]
    reset = fixture["reset"]
    mutate = fixture["mutate"]
    cleanup = fixture["cleanup"]
    expected = {
        "NF-03": "h_b_source_map_mismatch",
        "NF-04": "current_pol_identity_required",
        "NF-23": "stable_fd_drift",
        "NF-27": "replay_detected",
    }
    baseline = json.loads((root / envelope_path).read_text())
    proof = m._runtime_attestation_proof(root, baseline)

    def invoke(stage: str) -> None:
        if stage == "producer":
            m.produce_envelope(
                root,
                contract_path=contract_path,
                bundle_path=envelope_path,
                runtime_proof=proof,
            )
        else:
            m.consume_envelope(
                root,
                contract_path=contract_path,
                envelope_path=envelope_path,
                runtime_proof=proof,
            )

    try:
        for case_id, expected_code in expected.items():
            for stage in ("producer", "consumer"):
                reset()
                invoke(stage)
                reset()
                mutate(case_id)
                with pytest.raises(m.GateError) as error:
                    invoke(stage)
                assert error.value.code == expected_code
                reset()
                invoke(stage)
    finally:
        cleanup()


def test_verify_hb3_commit_positive_five_artifacts_and_v2_preserved(
    tmp_path: Path,
) -> None:
    root, contract, attempt = _full_hb3_fixture(tmp_path)
    binding_path = _install_hb3_commit_fixture(root, contract, attempt)
    result = m.verify_hb3_commit(
        root,
        contract_path="docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json",
        binding_path=binding_path,
    )
    binding = json.loads((root / binding_path).read_text())
    marker = json.loads((root / binding["external_commit_marker"]["path"]).read_text())
    assert result["status"] == "pass" and result["H_B_CURRENT"] is True
    assert set(binding) >= {
        "readiness",
        "receipt",
        "selected_dev",
        "selected_qa",
        "external_commit_marker",
    }
    assert marker["predecessor_v2"] == {
        "receipt_path": m.V2_RECEIPT,
        "receipt_sha256": m.V2_RECEIPT_SHA,
        "preserved": True,
        "current_revoked": True,
    }


@pytest.mark.parametrize(
    "path,expected_code",
    [
        ("scripts/spec-check.py", "h_b_untouched_provider_drift"),
        ("scripts/laneb-integration-gate.py", "h_b_dev_file_binding_mismatch"),
    ],
)
def test_full_hb3_provider_set_rejects_current_byte_drift(
    tmp_path: Path, path: str, expected_code: str
) -> None:
    root, _contract_value, attempt = _full_hb3_fixture(tmp_path)
    target = root / path
    target.write_bytes(target.read_bytes() + b"\n# drift\n")
    with pytest.raises(m.GateError) as error:
        m.verify_hb3_provider_set(
            root,
            contract_path="docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json",
            registry_path=m.REGISTRY_DEFAULT,
            attempt_id=attempt,
        )
    assert error.value.code == expected_code


def _transaction_fixture(tmp_path: Path, crash_after: int | None = None) -> Path:
    (tmp_path / ".laneb-throwaway-transaction-root").write_text("fixture")
    (tmp_path / "cycle.json").write_bytes(b"cycle-before")
    (tmp_path / "ledger.json").write_bytes(b"ledger-before")
    outputs = [
        {
            "path": f"steps/s{step}.json",
            "hex": f"step-{step}".encode().hex(),
            "step": step,
        }
        for step in range(1, 6)
    ] + [{"path": "marker.json", "hex": b"marker-last".hex(), "step": 6}]
    spec = {
        "lock": "lock",
        "cycle": "cycle.json",
        "ledger": "ledger.json",
        "cycle_before_hex": b"cycle-before".hex(),
        "cycle_after_hex": b"cycle-after".hex(),
        "ledger_before_hex": b"ledger-before".hex(),
        "ledger_after_hex": b"ledger-after".hex(),
        "outputs": outputs,
        "crash_after": crash_after,
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec, sort_keys=True))
    return path


def test_sandbox_transaction_s0_s6_marker_last_and_idempotent(tmp_path: Path) -> None:
    _transaction_fixture(tmp_path)
    result = m.sandbox_transaction(tmp_path, "spec.json")
    assert result["status"] == "pass" and result["state"] == "S6_COMMITTED"
    assert result["written"][-1] == "marker.json"
    assert result["marker_installed_last"] is True
    assert (tmp_path / "cycle.json").read_bytes() == b"cycle-after"
    assert (tmp_path / "ledger.json").read_bytes() == b"ledger-after"
    again = m.sandbox_transaction(tmp_path, "spec.json")
    assert again["status"] == "pass" and again["idempotent"] is True


@pytest.mark.parametrize("step", range(1, 6))
def test_sandbox_transaction_crash_each_step_resumes_without_early_marker(
    tmp_path: Path, step: int
) -> None:
    spec_path = _transaction_fixture(tmp_path, step)
    crashed = m.sandbox_transaction(tmp_path, spec_path.name)
    assert crashed["status"] == "recovery_required"
    assert not (tmp_path / "marker.json").exists()
    spec = json.loads(spec_path.read_text())
    spec["crash_after"] = None
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    resumed = m.sandbox_transaction(tmp_path, spec_path.name)
    assert resumed["status"] == "pass" and resumed["state"] == "S6_COMMITTED"
    assert (tmp_path / "marker.json").read_bytes() == b"marker-last"


@pytest.mark.parametrize("step", [3, 4, 5])
def test_sandbox_transaction_reverse_rollback_before_s6_preserves_evidence(
    tmp_path: Path, step: int
) -> None:
    spec_path = _transaction_fixture(tmp_path, step)
    m.sandbox_transaction(tmp_path, spec_path.name)
    spec = json.loads(spec_path.read_text())
    spec["action"] = "rollback"
    spec["crash_after"] = None
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    result = m.sandbox_transaction(tmp_path, spec_path.name)
    assert result["status"] == "terminal_no_authority"
    assert result["rollback_order"] == ["cycle", "ledger"]
    assert (tmp_path / "cycle.json").read_bytes() == b"cycle-before"
    assert (tmp_path / "ledger.json").read_bytes() == b"ledger-before"
    assert (tmp_path / "steps/s1.json").is_file()


def test_sandbox_transaction_forbids_rollback_after_s6(tmp_path: Path) -> None:
    spec_path = _transaction_fixture(tmp_path)
    m.sandbox_transaction(tmp_path, spec_path.name)
    spec = json.loads(spec_path.read_text())
    spec["action"] = "rollback"
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    with pytest.raises(m.GateError) as error:
        m.sandbox_transaction(tmp_path, spec_path.name)
    assert error.value.code == "control_plane_cas_invalid"
    assert (tmp_path / "marker.json").is_file()


def test_sandbox_transaction_rejects_marker_not_last_and_path_escape(
    tmp_path: Path,
) -> None:
    spec_path = _transaction_fixture(tmp_path)
    spec = json.loads(spec_path.read_text())
    spec["outputs"][0], spec["outputs"][-1] = spec["outputs"][-1], spec["outputs"][0]
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    with pytest.raises(m.GateError):
        m.sandbox_transaction(tmp_path, spec_path.name)
    spec = json.loads(_transaction_fixture(tmp_path).read_text())
    spec["outputs"][0]["path"] = "../escape"
    spec_path.write_text(json.dumps(spec, sort_keys=True))
    with pytest.raises(m.GateError):
        m.sandbox_transaction(tmp_path, spec_path.name)


def test_registry_rejects_nonce_or_transaction_cross_attempt_replay(
    tmp_path: Path,
) -> None:
    contract = _contract()
    first = _event(
        contract,
        sequence=1,
        kind="GATE_REPAIR_HB3",
        attempt="a000001",
        event_type="ALLOCATED",
        outcome="none",
        previous=None,
    )
    second = _event(
        contract,
        sequence=2,
        kind="FINAL_FAN_IN",
        attempt="a000001",
        event_type="ALLOCATED",
        outcome="none",
        previous=_sha(_canonical(first)),
    )
    second["nonce"] = first["nonce"]
    payload = copy.deepcopy(second)
    del payload["integrity"]["event_payload_sha256"]
    second["integrity"]["event_payload_sha256"] = m.canonical_sha(payload)
    (tmp_path / "r").write_bytes(_canonical(first) + b"\n" + _canonical(second) + b"\n")
    with m.CaptureSet(tmp_path) as captures:
        cap = captures.capture("r")
        with pytest.raises(m.GateError) as error:
            m.replay_registry(contract, cap)
    assert error.value.code == "replay_detected"


# ---------------------------------------------------------------------------
# Registry-v4 repair-v2 contract: 54 predecessor plus 29 repair cases.
# ---------------------------------------------------------------------------
V4_CONTEXT_PATH = ROOT / "docs/dev/context-20260815-lane-b-registry-v4-migration.json"
V4_CONTEXT = json.loads(V4_CONTEXT_PATH.read_text())
V4_REPAIR_CONTEXT_PATH = (
    ROOT / "docs/dev/context-20260815-lane-b-registry-v4-repair-v2.json"
)
V4_REPAIR_CONTEXT = json.loads(V4_REPAIR_CONTEXT_PATH.read_text())
V4_CASES = [
    (category, case)
    for category in ("positive", "negative", "concurrency", "crash_recovery", "tamper")
    for case in V4_CONTEXT["test_contract"]["new_logical_cases"][category]
]
assert len(V4_CASES) == 54
assert len({case["id"] for _, case in V4_CASES}) == 54
assert len({case["name"] for _, case in V4_CASES}) == 54
V4_REPAIR_CASES = [
    (category, case)
    for category in ("positive", "negative", "concurrency", "crash_recovery", "tamper")
    for case in V4_REPAIR_CONTEXT["test_contract"]["repair_logical_cases"][category]
]
assert len(V4_REPAIR_CASES) == 29
assert len({case["id"] for _, case in V4_REPAIR_CASES}) == 29
assert len({case["name"] for _, case in V4_REPAIR_CASES}) == 29


def _v4_fixture(root: Path) -> dict:
    context = copy.deepcopy(V4_CONTEXT)
    context.update(copy.deepcopy(V4_REPAIR_CONTEXT))
    copied = {
        m.V4_CONTEXT_DEFAULT,
        m.V4_TICKET_PATH,
        m.V4_BA_QA_PATH,
        m.V4_PARENT_ADMISSION_PATH,
        *(item["path"] for item in V4_CONTEXT["authoritative_predecessors"].values()),
        *(
            item["path"]
            for item in V4_REPAIR_CONTEXT["authoritative_inputs"].values()
            if isinstance(item, dict) and "path" in item
        ),
        *context["provider_binding_repair"]["provider_policy"]["fixed_provider_map"],
        *context["provider_binding_repair"]["provider_policy"][
            "mutable_provider_paths"
        ],
        *context["provider_binding_repair"]["consumer_map"],
    }
    for rel in sorted(copied):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / rel
        target.write_bytes(source.read_bytes())
        target.chmod(stat.S_IMODE(source.stat().st_mode))
    materialized = [
        context["v4_artifacts"]["registry"]["path"],
        context["v4_artifacts"]["migration_record"]["path"],
        context["v4_artifacts"]["migration_audit"]["path"],
        context["lock_CAS_and_safety"]["lock_path"],
        *[
            value.replace("{attempt_id}", "a000015")
            for value in context["allocator_contract"]["derived_paths"].values()
        ],
    ]
    for rel in materialized:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
    marker = root / ".laneb-v4-throwaway-root"
    marker.write_bytes(b"LANEB_V4_THROWAWAY\n")
    marker.chmod(0o600)
    lock = root / context["lock_CAS_and_safety"]["lock_path"]
    lock.touch(mode=0o644)
    return context


def _v4_cli(
    root: Path,
    phase: str,
    *args: str,
    timeout: float = 20,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--project-root",
            str(root),
            "--phase",
            phase,
            "--v4-test-mode",
            *args,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            **(extra_env or {}),
        },
    )


def _v4_output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stderr == ""
    assert result.stdout.endswith("\n") and result.stdout.count("\n") == 1
    value = json.loads(result.stdout)
    assert result.stdout.encode() == _canonical(value) + b"\n"
    assert value["G2_provider_satisfied"] is False
    assert value["authorization_effect"] == "none"
    assert value["authorizes"] == []
    return value


def _v4_commit(
    root: Path, *, crash: str | None = None
) -> subprocess.CompletedProcess[str]:
    args = ["--v4-event-at", "2026-08-15T08:00:00Z"]
    if crash:
        args += ["--v4-crash-after", crash]
    return _v4_cli(root, "registry-v4-migration-commit", *args)


def _v4_publish_audit(root: Path, context: dict) -> None:
    with m.V4Root(root) as safe:
        _cap, loaded = m._v4_context(safe, m.V4_CONTEXT_DEFAULT)
        record, _value = m._v4_record(
            safe, loaded, context["v4_artifacts"]["migration_record"]["path"]
        )
        registry = safe.read(context["v4_artifacts"]["registry"]["path"], modes={0o600})
        assert registry is not None
        audit = m.v4_expected_migration_audit(
            loaded,
            record,
            registry,
            "fresh-independent-migration-qa",
            "2026-08-15T08:01:00Z",
        )
    path = root / context["v4_artifacts"]["migration_audit"]["path"]
    path.write_bytes(m._v4_json_line(audit))
    path.chmod(0o444)


def _v4_activate(root: Path, context: dict) -> None:
    result = _v4_commit(root)
    assert result.returncode == 0, result.stdout
    _v4_publish_audit(root, context)


def _v4_allocate(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _v4_cli(
        root,
        "registry-v4-allocate",
        "--v4-event-at",
        "2026-08-15T08:02:00Z",
        *extra,
    )


def _v4_read_state(root: Path, context: dict) -> tuple[m.V4File, m.V4Replay, dict]:
    with m.V4Root(root) as safe:
        _cap, loaded = m._v4_context(safe, m.V4_CONTEXT_DEFAULT)
        record, _record_value = m._v4_record(
            safe, loaded, context["v4_artifacts"]["migration_record"]["path"]
        )
        registry = safe.read(context["v4_artifacts"]["registry"]["path"], modes={0o600})
        assert registry is not None
        replay = m._v4_replay(loaded, registry, record)
        return registry, replay, loaded


def _v4_write_artifact(root: Path, rel: str, value: dict, mode: int = 0o444) -> dict:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m._v4_json_line(value))
    path.chmod(mode)
    st = path.stat()
    return {
        "path": rel,
        "bytes": st.st_size,
        "sha256": _sha(path.read_bytes()),
        "mode": f"{stat.S_IMODE(st.st_mode):04o}",
        "nlink": st.st_nlink,
        "state": "file",
        "symlink": False,
    }


def _v4_file_ref(root: Path, rel: str) -> dict:
    path = root / rel
    data = path.read_bytes()
    item = path.stat()
    return {
        "path": rel,
        "bytes": len(data),
        "sha256": _sha(data),
        "mode": f"{stat.S_IMODE(item.st_mode):04o}",
        "nlink": item.st_nlink,
        "state": "file",
        "symlink": False,
    }


def _v4_live_binding_fixture(root: Path, context: dict) -> dict:
    repair = context["provider_binding_repair"]
    policy = repair["provider_policy"]
    provider_paths = [
        *policy["fixed_provider_map"],
        *policy["mutable_provider_paths"],
    ]
    provider_map = {path: _sha((root / path).read_bytes()) for path in provider_paths}
    assert {
        path: provider_map[path] for path in policy["fixed_provider_map"]
    } == policy["fixed_provider_map"]
    consumer_map = {
        path: _sha((root / path).read_bytes()) for path in repair["consumer_map"]
    }
    assert consumer_map == repair["consumer_map"]
    return {
        "provider_path_count": 16,
        "provider_map_sha256": m.canonical_sha(provider_map),
        "provider_policy_sha256": m.V4_PROVIDER_POLICY_SHA256,
        "fixed_provider_match": True,
        "mutable_provider_evidence_match": True,
        "consumer_path_count": 3,
        "consumer_map_sha256": m.canonical_sha(consumer_map),
        "consumer_map_verified": True,
    }


def _v4_no_authority() -> dict:
    return {
        "effect": "none",
        "G2_allowed": False,
        "H_B_final_allowed": False,
        "POL_allowed": False,
        "BIND_allowed": False,
        "close_allowed": False,
        "commit_allowed": False,
        "completion_allowed": False,
    }


def _v4_test_totals() -> dict:
    return {
        "collected": 346,
        "passed": 346,
        "failed": 0,
        "existing_regression": 263,
        "new_logical_cases": 83,
        "partition": {
            "positive": 14,
            "negative": 40,
            "concurrency": 8,
            "crash_recovery": 9,
            "tamper": 12,
        },
    }


def _v4_build_event(
    root: Path, context: dict, event_type: str, *, salt: str = "0"
) -> dict:
    registry, replay, loaded = _v4_read_state(root, context)
    allocation = next(
        row for row in replay.rows if row.get("event_type") == "ALLOCATED"
    )
    started = next(
        (row for row in reversed(replay.rows) if row.get("event_type") == "STARTED"),
        None,
    )
    committed = next(
        (
            row
            for row in reversed(replay.rows)
            if row.get("event_type") == "COMMIT_READY"
        ),
        None,
    )
    tx = hashlib.sha256(
        f"tx:{event_type}:{len(replay.rows)}:{salt}".encode()
    ).hexdigest()[:32]
    nonce = hashlib.sha256(
        f"nonce:{event_type}:{len(replay.rows)}:{salt}".encode()
    ).hexdigest()[:32]
    now = dt.datetime.now(dt.timezone.utc)

    def stamp(seconds: int) -> str:
        return (now + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    event = {
        "schema_version": 4,
        "record_type": "lane_b_attempt_identity_registry_v4_event",
        "event_sequence": len(replay.rows) + 1,
        "previous_event_sha256": replay.head_sha256,
        "event_type": event_type,
        "attempt_kind": allocation["attempt_kind"],
        "attempt_id": allocation["attempt_id"],
        "attempt_sequence": allocation["attempt_sequence"],
        "attempt_uid": allocation["attempt_uid"],
        "transaction_id": tx,
        "nonce": nonce,
        "identity": copy.deepcopy(allocation["identity"]),
        "owner_role": "same_spec_parent",
        "derived_paths": copy.deepcopy(allocation["derived_paths"]),
        "migration_identity": None,
        "dev_dispatch_identity": None,
        "qa_dispatch_identity": None,
        "producer_identity": None,
        "qa_result_identity": None,
        "readiness_identity": None,
        "receipt_identity": None,
        "marker_identity": None,
        "recovery_identity": None,
        "terminal_failure_identity": None,
        "binding_identity": None,
        "precondition_manifest_sha256": "0" * 64,
        "event_at": stamp(0),
        "outcome": "pending",
        "authorization_effect": "none",
        "integrity": {"canonicalization": m.V4_INTEGRITY_LANGUAGE},
    }
    dispatch = {
        "dispatch_id": "real-dev-dispatch-a000015",
        "task_id": "GATE_REPAIR_HB3-a000015",
        "agent_id": "fresh-dev-a000015",
        "role": "lane_b_dev",
        "dispatched_at": stamp(-30),
        "ticket_sha256": m.V4_TICKET_SHA256,
        "context_sha256": m.V4_CONTEXT_SHA256,
        "real_dispatch": True,
        "synthetic": False,
        "same_lane": True,
    }
    if event_type == "STARTED":
        event["event_at"] = stamp(-29)
        event["dev_dispatch_identity"] = dispatch
    elif event_type in {"COMMIT_READY", "TERMINAL_EVIDENCE_READY"}:
        assert started is not None
        event["dev_dispatch_identity"] = copy.deepcopy(started["dev_dispatch_identity"])
        event["outcome"] = (
            "pass_ready"
            if event_type == "COMMIT_READY"
            else "evidence_ready_for_g2_reaudit"
        )
        paths = allocation["derived_paths"]
        if committed is None:
            identity = m._v4_attempt_identity(event)
            started_sha = _sha(m._v4_json_line(started)[:-1])
            bundle = _sha(f"bundle:{salt}:{started_sha}".encode())
            binding = _v4_live_binding_fixture(root, context)
            implementation_files = [
                _v4_file_ref(root, rel)
                for rel in context["provider_binding_repair"]["provider_policy"][
                    "mutable_provider_paths"
                ]
            ]
            evidence_dispatch = {
                **event["dev_dispatch_identity"],
                "ba_qa_sha256": m.V4_BA_QA_SHA256,
                "parent_admission_sha256": m.V4_PARENT_ADMISSION_SHA256,
            }
            producer = _v4_write_artifact(
                root,
                paths["dev_report"],
                {
                    "schema_name": "lane_b_registry_v4_producer_evidence.v2",
                    "schema_version": 2,
                    "record_type": "real_dev_producer_evidence",
                    "status": "PASS",
                    "created_at": stamp(-5),
                    "identity": identity,
                    "evidence_bundle_id": bundle,
                    "started_event_sha256": started_sha,
                    "dev_dispatch": evidence_dispatch,
                    "ticket_sha256": m.V4_TICKET_SHA256,
                    "context_sha256": m.V4_CONTEXT_SHA256,
                    "implementation_files": implementation_files,
                    "changed_paths": [
                        "scripts/laneb-integration-gate.py",
                        "hooks/tests/test_laneb_integration_gate.py",
                    ],
                    "tests": _v4_test_totals(),
                    "binding": binding,
                    "authorization": _v4_no_authority(),
                },
            )
            qa_dispatch = {
                **dispatch,
                "dispatch_id": "fresh-independent-qa-dispatch-a000015",
                "agent_id": "fresh-qa-a000015",
                "role": "independent_lane_b_qa",
                "dispatched_at": stamp(-4),
            }
            evidence_qa_dispatch = {
                **qa_dispatch,
                "ba_qa_sha256": m.V4_BA_QA_SHA256,
                "parent_admission_sha256": m.V4_PARENT_ADMISSION_SHA256,
            }
            qa = _v4_write_artifact(
                root,
                paths["qa_report"],
                {
                    "schema_name": "lane_b_registry_v4_independent_qa_evidence.v2",
                    "schema_version": 2,
                    "record_type": "fresh_independent_implementation_qa",
                    "status": "PASS",
                    "verdict": "PASS",
                    "started_at": stamp(-3),
                    "finalized_at": stamp(-2),
                    "identity": identity,
                    "evidence_bundle_id": bundle,
                    "started_event_sha256": started_sha,
                    "qa_dispatch": evidence_qa_dispatch,
                    "qa_agent_id": qa_dispatch["agent_id"],
                    "dev_agent_id": event["dev_dispatch_identity"]["agent_id"],
                    "independent": True,
                    "producer": producer,
                    "observed_implementation_files": implementation_files,
                    "tests": _v4_test_totals(),
                    "binding": binding,
                    "freshness": {
                        "validation_time": stamp(4),
                        "max_age_seconds": 3600,
                        "max_future_skew_seconds": 5,
                        "within_window": True,
                    },
                    "authorization": _v4_no_authority(),
                },
            )
            readiness = _v4_write_artifact(
                root,
                paths["readiness"],
                {
                    "schema_name": "lane_b_registry_v4_consumer_handoff_readiness.v2",
                    "schema_version": 2,
                    "record_type": "closed_evidence_readiness",
                    "status": "READY_FOR_COMMIT_READY_ONLY",
                    "created_at": stamp(-1),
                    "identity": identity,
                    "evidence_bundle_id": bundle,
                    "started_event_sha256": started_sha,
                    "producer": producer,
                    "qa": qa,
                    "binding": binding,
                    "all_inputs_exact": True,
                    "authorization": _v4_no_authority(),
                },
            )
            receipt = _v4_write_artifact(
                root,
                paths["receipt"],
                {
                    "schema_name": "lane_b_registry_v4_evidence_repair_receipt.v2",
                    "schema_version": 2,
                    "record_type": "closed_evidence_receipt",
                    "status": "RECEIPT_EXACT_NON_AUTHORIZING",
                    "created_at": stamp(0),
                    "identity": identity,
                    "evidence_bundle_id": bundle,
                    "started_event_sha256": started_sha,
                    "producer": producer,
                    "qa": qa,
                    "readiness": readiness,
                    "binding": binding,
                    "authorization": _v4_no_authority(),
                },
            )
            event.update(
                qa_dispatch_identity=qa_dispatch,
                producer_identity=producer,
                qa_result_identity=qa,
                readiness_identity=readiness,
                receipt_identity=receipt,
                binding_identity={
                    **binding,
                },
            )
        else:
            for key in (
                "dev_dispatch_identity",
                "qa_dispatch_identity",
                "producer_identity",
                "qa_result_identity",
                "readiness_identity",
                "receipt_identity",
                "binding_identity",
            ):
                event[key] = copy.deepcopy(committed[key])
            marker = _v4_write_artifact(
                root,
                paths["commit_marker"],
                {
                    "schema_name": "lane_b_registry_v4_terminal_evidence_marker.v2",
                    "schema_version": 2,
                    "record_type": "closed_terminal_evidence_marker",
                    "status": "EVIDENCE_READY_FOR_G2_REAUDIT_ONLY",
                    "created_at": stamp(0),
                    "identity": m._v4_attempt_identity(event),
                    "evidence_bundle_id": json.loads(
                        (root / paths["dev_report"]).read_text()
                    )["evidence_bundle_id"],
                    "started_event_sha256": _sha(m._v4_json_line(started)[:-1]),
                    "producer": event["producer_identity"],
                    "qa": event["qa_result_identity"],
                    "readiness": event["readiness_identity"],
                    "receipt": event["receipt_identity"],
                    "commit_ready_event_sha256": _sha(m._v4_json_line(committed)[:-1]),
                    "binding": event["binding_identity"],
                    "authorization": _v4_no_authority(),
                },
            )
            event["marker_identity"] = marker
    elif event_type == "RECOVERY_REQUIRED":
        assert started is not None
        event["dev_dispatch_identity"] = copy.deepcopy(started["dev_dispatch_identity"])
        journal = _v4_write_artifact(
            root,
            allocation["derived_paths"]["recovery_manifest"],
            {"attempt_id": "a000015", "status": "RECOVERY_REQUIRED"},
        )
        event["recovery_identity"] = {
            "phase": "INTENT_DURABLE",
            "journal": journal,
            "observed_prefix_bytes": 0,
            "observed_prefix_sha256": _sha(b""),
            "cause_sha256": _sha(b"crash"),
        }
        event["outcome"] = "crash_detected"
    event["precondition_manifest_sha256"] = m.v4_transition_precondition(
        registry, event
    )
    return m._v4_with_integrity(event)


def _v4_transition(
    root: Path, context: dict, event: dict, *, crash: str | None = None
) -> subprocess.CompletedProcess[str]:
    path = root / "input" / "event.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m._v4_json_line(event))
    path.chmod(0o644)
    args = ["--event-input", "input/event.json"]
    if crash:
        args += ["--v4-crash-after", crash]
    return _v4_cli(root, "registry-v4-transition", *args)


def _v4_start(root: Path, context: dict) -> None:
    result = _v4_transition(root, context, _v4_build_event(root, context, "STARTED"))
    assert result.returncode == 0, result.stdout


def _v4_commit_ready(root: Path, context: dict) -> None:
    _v4_start(root, context)
    result = _v4_transition(
        root, context, _v4_build_event(root, context, "COMMIT_READY")
    )
    assert result.returncode == 0, result.stdout


def _v4_find_intent_tx(root: Path, context: dict, *, non_genesis: bool = False) -> str:
    parent = root / Path(context["v4_artifacts"]["registry"]["path"]).parent
    items = sorted(parent.glob("lane-b-registry-v4-transaction.*.step-01-intent.json"))
    for path in reversed(items):
        value = json.loads(path.read_text())
        line = bytes.fromhex(value["intended_event_hex"])
        event = json.loads(line)
        if not non_genesis or event["event_type"] != "MIGRATION_GENESIS":
            return value["transaction_id"]
    raise AssertionError("intent not found")


def _v4_recover_cli(root: Path, tx: str) -> subprocess.CompletedProcess[str]:
    return _v4_cli(root, "registry-v4-recover", "--transaction-id", tx)


@pytest.mark.parametrize(
    ("category", "case"),
    V4_CASES,
    ids=[f'{case["id"]}-{case["name"]}' for _category, case in V4_CASES],
)
def test_registry_v4_contract_case_matrix(
    tmp_path: Path, category: str, case: dict
) -> None:
    context = _v4_fixture(tmp_path)
    case_id = case["id"]

    if category == "positive":
        if case_id in {"V4-P01", "V4-P02", "V4-P10"}:
            result = _v4_cli(tmp_path, "registry-v4-migration-preflight")
            output = _v4_output(result)
            assert result.returncode == 0
            assert output["result"]["legacy"]["strict_valid_count"] == 1
            assert output["result"]["legacy"]["strict_invalid_count"] == 7
            if case_id == "V4-P01":
                for key in (
                    "event_schema",
                    "migration_record_schema",
                    "migration_audit_schema",
                ):
                    schema = context["closed_schemas"][key]
                    m.jsonschema.Draft202012Validator.check_schema(schema)
            return
        _v4_activate(tmp_path, context)
        if case_id == "V4-P03":
            registry = tmp_path / context["v4_artifacts"]["registry"]["path"]
            assert len(registry.read_bytes().splitlines()) == 1
            return
        if case_id == "V4-P04":
            result = _v4_allocate(tmp_path)
            assert (
                result.returncode == 0
                and _v4_output(result)["result"]["attempt_id"] == "a000015"
            )
            return
        if case_id == "V4-P05":
            result = _v4_commit(tmp_path)
            assert result.returncode == 0
            assert _v4_output(result)["result"]["result"] == "ALREADY_COMMITTED_EXACT"
            return
        result = _v4_allocate(tmp_path)
        assert result.returncode == 0
        if case_id == "V4-P06":
            value = _v4_output(result)["result"]
            assert (
                value["attempt_id"] == "a000015" and len(value["derived_paths"]) == 14
            )
            return
        _v4_start(tmp_path, context)
        if case_id == "V4-P07":
            return
        commit = _v4_transition(
            tmp_path, context, _v4_build_event(tmp_path, context, "COMMIT_READY")
        )
        assert commit.returncode == 0
        if case_id == "V4-P08":
            return
        terminal = _v4_transition(
            tmp_path,
            context,
            _v4_build_event(tmp_path, context, "TERMINAL_EVIDENCE_READY"),
        )
        assert terminal.returncode == 0
        verify = _v4_cli(
            tmp_path, "verify-h-b-v4-provider-set", "--attempt-id", "a000015"
        )
        value = _v4_output(verify)
        assert verify.returncode == 0 and value["result"]["G2_reaudit_eligible"] is True
        return

    if category == "negative":
        v3 = tmp_path / context["legacy_v3_quarantine_contract"]["source"]["path"]
        if case_id in {"V4-N01", "V4-N02", "V4-N03", "V4-N05", "V4-N06", "V4-N20"}:
            before = v3.read_bytes()
            if case_id == "V4-N02":
                v3.write_bytes(b"".join(reversed(before.splitlines(keepends=True))))
            elif case_id == "V4-N20":
                v3.chmod(0o644)
            else:
                v3.write_bytes(before[:-2] + b"X\n")
            result = _v4_cli(tmp_path, "registry-v4-migration-preflight")
            assert result.returncode in {2, 3}
            _v4_output(result)
            if case_id == "V4-N20":
                assert v3.read_bytes() == before
            return
        if case_id == "V4-N04":
            result = _v4_cli(tmp_path, "registry-v4-migration-preflight")
            assert result.returncode == 0
            assert (
                _v4_output(result)["result"]["legacy"]["line2_normative_link_valid"]
                is False
            )
            return
        if case_id == "V4-N08":
            other = tmp_path / "other-v3.jsonl"
            other.write_bytes(v3.read_bytes())
            result = _v4_cli(
                tmp_path,
                "registry-v4-migration-preflight",
                "--v3-registry",
                "other-v3.jsonl",
            )
            assert result.returncode == 2
            return
        _v4_activate(tmp_path, context)
        if case_id == "V4-N07":
            (tmp_path / context["v4_artifacts"]["migration_audit"]["path"]).unlink()
            assert _v4_allocate(tmp_path).returncode == 2
            return
        if case_id in {"V4-N09", "V4-N10"}:
            token = "a999999" if case_id == "V4-N09" else "a000014"
            assert _v4_allocate(tmp_path, "--attempt-id", token).returncode == 2
            return
        if case_id in {"V4-N11", "V4-N12"}:
            kind = "FINAL_FAN_IN" if case_id == "V4-N11" else "POL_EXTERNAL"
            assert _v4_allocate(tmp_path, "--attempt-kind", kind).returncode == 2
            return
        assert _v4_allocate(tmp_path).returncode == 0
        started = _v4_build_event(tmp_path, context, "STARTED")
        if case_id == "V4-N13":
            started["dev_dispatch_identity"]["synthetic"] = True
            started = m._v4_with_integrity(started)
            assert _v4_transition(tmp_path, context, started).returncode == 2
            return
        assert _v4_transition(tmp_path, context, started).returncode == 0
        commit = _v4_build_event(tmp_path, context, "COMMIT_READY")
        if case_id == "V4-N14":
            commit["producer_identity"] = None
        elif case_id == "V4-N15":
            qa_path = tmp_path / commit["qa_result_identity"]["path"]
            qa = json.loads(qa_path.read_text())
            qa["status"] = "FAIL"
            qa_path.write_bytes(m._v4_json_line(qa))
            commit["qa_result_identity"]["bytes"] = qa_path.stat().st_size
            commit["qa_result_identity"]["sha256"] = _sha(qa_path.read_bytes())
        elif case_id == "V4-N16":
            (tmp_path / commit["readiness_identity"]["path"]).unlink()
        elif case_id == "V4-N17":
            commit["qa_dispatch_identity"]["agent_id"] = commit[
                "dev_dispatch_identity"
            ]["agent_id"]
        elif case_id == "V4-N18":
            commit["binding_identity"]["provider_path_count"] = 15
        elif case_id == "V4-N19":
            commit["authorization_effect"] = "G2"
        registry, _replay, _loaded = _v4_read_state(tmp_path, context)
        commit["precondition_manifest_sha256"] = m.v4_transition_precondition(
            registry, commit
        )
        commit = m._v4_with_integrity(commit)
        assert _v4_transition(tmp_path, context, commit).returncode in {2, 3}
        return

    if category == "concurrency":
        _v4_activate(tmp_path, context)
        if case_id == "V4-C06":
            lock_rel = context["lock_CAS_and_safety"]["lock_path"]
            before = (tmp_path / lock_rel).read_bytes()
            with m.V4Root(tmp_path) as safe:
                with m._v4_lock(safe, lock_rel, 0):
                    result = _v4_cli(
                        tmp_path, "registry-v4-allocate", "--lock-timeout", "0"
                    )
            assert (
                result.returncode == 4 and (tmp_path / lock_rel).read_bytes() == before
            )
            return
        if case_id in {"V4-C01", "V4-C02"}:
            commands = [
                [
                    sys.executable,
                    str(GATE),
                    "--project-root",
                    str(tmp_path),
                    "--phase",
                    "registry-v4-allocate",
                    "--v4-test-mode",
                    "--lock-timeout",
                    "2",
                ]
                for _ in range(2)
            ]
            procs = [
                subprocess.Popen(
                    cmd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                for cmd in commands
            ]
            results = [
                proc.communicate(timeout=20) + (proc.returncode,) for proc in procs
            ]
            assert sorted(item[2] for item in results) == [0, 2]
            registry = tmp_path / context["v4_artifacts"]["registry"]["path"]
            assert (
                sum(
                    json.loads(line)["event_type"] == "ALLOCATED"
                    for line in registry.read_text().splitlines()
                )
                == 1
            )
            return
        assert _v4_allocate(tmp_path).returncode == 0
        event = _v4_build_event(tmp_path, context, "STARTED")
        event2 = copy.deepcopy(event)
        if case_id in {"V4-C04", "V4-C05"}:
            event2["transaction_id"] = hashlib.sha256(b"alternate-tx").hexdigest()[:32]
            event2["nonce"] = hashlib.sha256(b"alternate-nonce").hexdigest()[:32]
            event2 = m._v4_with_integrity(event2)
        if case_id == "V4-C04":
            assert _v4_transition(tmp_path, context, event).returncode == 0
            assert _v4_transition(tmp_path, context, event2).returncode == 3
            return
        event_path1 = tmp_path / "input" / "event1.json"
        event_path2 = tmp_path / "input" / "event2.json"
        event_path1.parent.mkdir(parents=True, exist_ok=True)
        event_path1.write_bytes(m._v4_json_line(event))
        event_path1.chmod(0o644)
        event_path2.write_bytes(m._v4_json_line(event2))
        event_path2.chmod(0o644)
        procs = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(GATE),
                    "--project-root",
                    str(tmp_path),
                    "--phase",
                    "registry-v4-transition",
                    "--v4-test-mode",
                    "--event-input",
                    f"input/event{index}.json",
                    "--lock-timeout",
                    "2",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            for index in (1, 2)
        ]
        results = [proc.communicate(timeout=20) + (proc.returncode,) for proc in procs]
        expected = [0, 0] if case_id == "V4-C03" else [0, 3]
        assert sorted(item[2] for item in results) == expected
        return

    if category == "crash_recovery":
        if case_id == "V4-R01":
            crashed = _v4_commit(tmp_path, crash="migration-record")
            assert crashed.returncode == 5
            assert _v4_commit(tmp_path).returncode == 0
            return
        if case_id == "V4-R02":
            crashed = _v4_commit(tmp_path, crash="fsync")
            assert crashed.returncode == 5
            tx = _v4_find_intent_tx(tmp_path, context)
            assert _v4_recover_cli(tmp_path, tx).returncode == 0
            return
        if case_id == "V4-R03":
            assert _v4_commit(tmp_path).returncode == 0
            assert _v4_allocate(tmp_path).returncode == 2
            return
        _v4_activate(tmp_path, context)
        crash = {
            "V4-R04": "intent",
            "V4-R05": "partial",
            "V4-R06": "append",
            "V4-R07": "fsync",
            "V4-R08": "partial",
        }[case_id]
        crashed = _v4_allocate(tmp_path, "--v4-crash-after", crash)
        assert crashed.returncode == 5
        tx = _v4_find_intent_tx(tmp_path, context, non_genesis=True)
        registry_path = tmp_path / context["v4_artifacts"]["registry"]["path"]
        if case_id == "V4-R08":
            data = bytearray(registry_path.read_bytes())
            data[-1] ^= 1
            registry_path.write_bytes(data)
            registry_path.chmod(0o600)
            before = registry_path.read_bytes()
            assert _v4_recover_cli(tmp_path, tx).returncode == 3
            assert registry_path.read_bytes() == before
        else:
            assert _v4_recover_cli(tmp_path, tx).returncode == 0
        return

    assert category == "tamper"
    _v4_activate(tmp_path, context)
    registry_path = tmp_path / context["v4_artifacts"]["registry"]["path"]
    if case_id == "V4-T01":
        target = tmp_path / "registry-real"
        registry_path.rename(target)
        registry_path.symlink_to(target)
        assert _v4_allocate(tmp_path).returncode == 3
    elif case_id == "V4-T02":
        escape = tmp_path / "escape"
        escape.symlink_to(registry_path.parent, target_is_directory=True)
        rel = f"escape/{registry_path.name}"
        assert (
            _v4_cli(tmp_path, "registry-v4-allocate", "--v4-registry", rel).returncode
            == 3
        )
    elif case_id == "V4-T03":
        os.link(registry_path, tmp_path / "registry-hardlink")
        assert _v4_allocate(tmp_path).returncode == 3
    elif case_id == "V4-T04":
        crashed = _v4_allocate(tmp_path, "--v4-crash-after", "intent")
        assert crashed.returncode == 5
        tx = _v4_find_intent_tx(tmp_path, context, non_genesis=True)
        data = registry_path.read_bytes()
        registry_path.unlink()
        registry_path.write_bytes(data)
        registry_path.chmod(0o600)
        assert _v4_recover_cli(tmp_path, tx).returncode == 3
    elif case_id == "V4-T05":
        registry_path.chmod(0o644)
        assert _v4_allocate(tmp_path).returncode == 3
    elif case_id == "V4-T06":
        registry_path.write_bytes(registry_path.read_bytes()[:-1])
        registry_path.chmod(0o600)
        assert _v4_allocate(tmp_path).returncode == 3
    elif case_id == "V4-T07":
        registry_path.write_bytes(b'{"x":1,"x":2}\n')
        registry_path.chmod(0o600)
        assert _v4_allocate(tmp_path).returncode == 3
    elif case_id == "V4-T08":
        row = json.loads(registry_path.read_text().splitlines()[0])
        row["integrity"]["event_payload_sha256"] = "0" * 64
        registry_path.write_bytes(_canonical(row) + b"\n")
        registry_path.chmod(0o600)
        assert _v4_allocate(tmp_path).returncode == 2
    elif case_id == "V4-T09":
        assert _v4_allocate(tmp_path).returncode == 0
        rows = [json.loads(line) for line in registry_path.read_text().splitlines()]
        rows[1]["previous_event_sha256"] = "0" * 64
        rows[1] = m._v4_with_integrity(rows[1])
        registry_path.write_bytes(b"".join(_canonical(row) + b"\n" for row in rows))
        registry_path.chmod(0o600)
        assert _v4_allocate(tmp_path).returncode == 3
    else:
        crashed = _v4_allocate(tmp_path, "--v4-crash-after", "intent")
        assert crashed.returncode == 5
        tx = _v4_find_intent_tx(tmp_path, context, non_genesis=True)
        intent = next(
            (tmp_path / Path(context["v4_artifacts"]["registry"]["path"]).parent).glob(
                f"lane-b-registry-v4-transaction.{tx}.step-01-intent.json"
            )
        )
        value = json.loads(intent.read_text())
        value["status"] = "TAMPERED"
        intent.write_bytes(_canonical(value) + b"\n")
        intent.chmod(0o444)
        assert _v4_recover_cli(tmp_path, tx).returncode == 3


def _v4_tree_identity(root: Path) -> dict[str, tuple]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        item = path.stat()
        result[path.relative_to(root).as_posix()] = (
            _sha(path.read_bytes()),
            item.st_size,
            stat.S_IMODE(item.st_mode),
            item.st_dev,
            item.st_ino,
            item.st_nlink,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
    return result


def _v4_reseal_event(root: Path, context: dict, event: dict) -> dict:
    registry, _replay, _loaded = _v4_read_state(root, context)
    event["precondition_manifest_sha256"] = m.v4_transition_precondition(
        registry, event
    )
    return m._v4_with_integrity(event)


def _v4_mutate_event_artifact(
    root: Path,
    event: dict,
    identity_field: str,
    mutate,
) -> dict:
    artifact = event[identity_field]
    value = json.loads((root / artifact["path"]).read_text())
    mutate(value)
    event[identity_field] = _v4_write_artifact(root, artifact["path"], value)
    return value


def _v4_prepared_commit_event(root: Path, context: dict) -> dict:
    _v4_activate(root, context)
    assert _v4_allocate(root).returncode == 0
    _v4_start(root, context)
    return _v4_build_event(root, context, "COMMIT_READY")


def _v4_assert_transition_denied(
    root: Path, context: dict, event: dict
) -> subprocess.CompletedProcess[str]:
    registry = root / context["v4_artifacts"]["registry"]["path"]
    before = registry.read_bytes()
    result = _v4_transition(root, context, _v4_reseal_event(root, context, event))
    assert result.returncode in {2, 3}
    _v4_output(result)
    assert registry.read_bytes() == before
    return result


def _v4_race_environment(root: Path, location: str) -> dict[str, str]:
    inject = root / "race-injection"
    inject.mkdir()
    (inject / "sitecustomize.py").write_text(
        """import os
_original_pread = os.pread
_changed = False
def _race_pread(fd, size, offset):
    global _changed
    data = _original_pread(fd, size, offset)
    if not _changed and offset == 0 and data:
        _changed = True
        value = bytearray(data)
        index = 0 if os.environ['LANEB_V4_RACE_LOCATION'] == 'first' else max(0, len(value) - 2)
        value[index] ^= 1
        return bytes(value)
    return data
os.pread = _race_pread
"""
    )
    return {
        "PYTHONPATH": str(inject),
        "LANEB_V4_RACE_LOCATION": location,
    }


def _v4_transition_with_env(
    root: Path, event: dict, extra_env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    path = root / "input" / "event.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m._v4_json_line(event))
    path.chmod(0o644)
    return _v4_cli(
        root,
        "registry-v4-transition",
        "--event-input",
        "input/event.json",
        extra_env=extra_env,
    )


@pytest.mark.parametrize(
    ("category", "case"),
    V4_REPAIR_CASES,
    ids=[f'{case["id"]}-{case["name"]}' for _category, case in V4_REPAIR_CASES],
)
def test_registry_v4_repair_v2_case_matrix(
    tmp_path: Path, category: str, case: dict
) -> None:
    context = _v4_fixture(tmp_path)
    case_id = case["id"]

    if category == "positive":
        if case_id == "V4R-P01":
            event = _v4_prepared_commit_event(tmp_path, context)
            result = _v4_transition(tmp_path, context, event)
            assert result.returncode == 0, result.stdout
            registry, replay, _loaded = _v4_read_state(tmp_path, context)
            assert replay.rows[-1]["event_type"] == "COMMIT_READY"
            assert replay.rows[-1]["binding_identity"] == _v4_live_binding_fixture(
                tmp_path, context
            )
            assert registry.data.endswith(m._v4_json_line(replay.rows[-1]))
            for name, digest in m.V4_EVIDENCE_SCHEMA_SHA256.items():
                schema = context["closed_schemas"][name + "_schema"]
                m.jsonschema.Draft202012Validator.check_schema(schema)
                assert m.canonical_sha(schema) == digest
            return
        if case_id == "V4R-P02":
            _v4_activate(tmp_path, context)
            assert _v4_allocate(tmp_path).returncode == 0
            _v4_commit_ready(tmp_path, context)
            terminal = _v4_transition(
                tmp_path,
                context,
                _v4_build_event(tmp_path, context, "TERMINAL_EVIDENCE_READY"),
            )
            assert terminal.returncode == 0, terminal.stdout
            verified = _v4_cli(
                tmp_path, "verify-h-b-v4-provider-set", "--attempt-id", "a000015"
            )
            output = _v4_output(verified)
            assert verified.returncode == 0
            assert output["result"]["G2_reaudit_eligible"] is True
            assert output["result"]["G2_provider_satisfied"] is False
            return
        _v4_activate(tmp_path, context)
        assert _v4_allocate(tmp_path).returncode == 0
        if case_id == "V4R-P04":
            _v4_start(tmp_path, context)
        before = _v4_tree_identity(tmp_path)
        result = _v4_commit(tmp_path)
        assert result.returncode == 0, result.stdout
        assert (
            _v4_output(result)["result"]["result"]
            == "ALREADY_COMMITTED_EXACT_WITH_VALID_TAIL"
        )
        assert _v4_tree_identity(tmp_path) == before
        return

    if category == "crash_recovery":
        _v4_activate(tmp_path, context)
        crashed = _v4_allocate(tmp_path, "--v4-crash-after", "partial")
        assert crashed.returncode == 5
        tx = _v4_find_intent_tx(tmp_path, context, non_genesis=True)
        assert _v4_recover_cli(tmp_path, tx).returncode == 0
        before = _v4_tree_identity(tmp_path)
        rerun = _v4_commit(tmp_path)
        assert rerun.returncode == 0
        assert (
            _v4_output(rerun)["result"]["result"]
            == "ALREADY_COMMITTED_EXACT_WITH_VALID_TAIL"
        )
        assert _v4_tree_identity(tmp_path) == before
        return

    if category == "concurrency":
        _v4_activate(tmp_path, context)
        assert _v4_allocate(tmp_path).returncode == 0
        event = _v4_build_event(tmp_path, context, "STARTED")
        registry = tmp_path / context["v4_artifacts"]["registry"]["path"]
        before = registry.read_bytes()
        location = "first" if case_id == "V4R-C01" else "head"
        result = _v4_transition_with_env(
            tmp_path, event, _v4_race_environment(tmp_path, location)
        )
        assert result.returncode == 3
        output = _v4_output(result)
        assert output["findings"][0]["code"] == "v4_cas_denied"
        assert registry.read_bytes() == before
        return

    if category == "tamper":
        event = _v4_prepared_commit_event(tmp_path, context)
        if case_id == "V4R-T01":
            rel = next(
                iter(
                    context["provider_binding_repair"]["provider_policy"][
                        "fixed_provider_map"
                    ]
                )
            )
        else:
            rel = next(iter(context["provider_binding_repair"]["consumer_map"]))
        path = tmp_path / rel
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        path.chmod(stat.S_IMODE((ROOT / rel).stat().st_mode))
        result = _v4_assert_transition_denied(tmp_path, context, event)
        assert result.returncode == 3
        return

    assert category == "negative"
    if case_id in {"V4R-N05", "V4R-N15"}:
        commit = _v4_prepared_commit_event(tmp_path, context)
        assert _v4_transition(tmp_path, context, commit).returncode == 0
        event = _v4_build_event(tmp_path, context, "TERMINAL_EVIDENCE_READY")
        if case_id == "V4R-N05":
            marker = event["marker_identity"]
            (tmp_path / marker["path"]).write_bytes(b"{}\n")
            (tmp_path / marker["path"]).chmod(0o444)
            event["marker_identity"] = _v4_file_ref(tmp_path, marker["path"])
        else:
            _v4_mutate_event_artifact(
                tmp_path,
                event,
                "marker_identity",
                lambda value: value.__setitem__("commit_ready_event_sha256", "0" * 64),
            )
        _v4_assert_transition_denied(tmp_path, context, event)
        return

    event = _v4_prepared_commit_event(tmp_path, context)
    if case_id == "V4R-N01":
        artifact = event["producer_identity"]
        (tmp_path / artifact["path"]).write_bytes(b"{}\n")
        (tmp_path / artifact["path"]).chmod(0o444)
        event["producer_identity"] = _v4_file_ref(tmp_path, artifact["path"])
    elif case_id == "V4R-N02":
        artifact = event["qa_result_identity"]
        (tmp_path / artifact["path"]).write_bytes(b"{}\n")
        (tmp_path / artifact["path"]).chmod(0o444)
        event["qa_result_identity"] = _v4_file_ref(tmp_path, artifact["path"])
    elif case_id == "V4R-N03":
        artifact = event["readiness_identity"]
        (tmp_path / artifact["path"]).write_bytes(b"{}\n")
        (tmp_path / artifact["path"]).chmod(0o444)
        event["readiness_identity"] = _v4_file_ref(tmp_path, artifact["path"])
    elif case_id == "V4R-N04":
        artifact = event["receipt_identity"]
        (tmp_path / artifact["path"]).write_bytes(b"{}\n")
        (tmp_path / artifact["path"]).chmod(0o444)
        event["receipt_identity"] = _v4_file_ref(tmp_path, artifact["path"])
    elif case_id == "V4R-N06":
        artifacts = {
            "producer_evidence": event["producer_identity"],
            "independent_qa_evidence": event["qa_result_identity"],
            "readiness": event["readiness_identity"],
            "receipt": event["receipt_identity"],
        }
        assert _v4_transition(tmp_path, context, event).returncode == 0
        terminal = _v4_build_event(tmp_path, context, "TERMINAL_EVIDENCE_READY")
        artifacts["marker"] = terminal["marker_identity"]
        for name, artifact in artifacts.items():
            value = json.loads((tmp_path / artifact["path"]).read_text())
            value["unexpected"] = True
            with pytest.raises(m.V4Error) as error:
                m._v4_schema(value, context["closed_schemas"][name + "_schema"])
            assert error.value.code == "v4_schema_invalid"
        return
    elif case_id == "V4R-N07":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "producer_identity",
            lambda value: value["identity"].__setitem__("attempt_id", "a000016"),
        )
    elif case_id == "V4R-N08":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "producer_identity",
            lambda value: value["implementation_files"][0].__setitem__(
                "sha256", "0" * 64
            ),
        )
    elif case_id == "V4R-N09":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "qa_result_identity",
            lambda value: value["identity"].__setitem__("attempt_id", "a000016"),
        )
    elif case_id == "V4R-N10":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "qa_result_identity",
            lambda value: value["producer"].__setitem__("sha256", "0" * 64),
        )
    elif case_id == "V4R-N11":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "qa_result_identity",
            lambda value: value.__setitem__("qa_agent_id", value["dev_agent_id"]),
        )
    elif case_id == "V4R-N12":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "qa_result_identity",
            lambda value: value["freshness"].__setitem__(
                "validation_time", "2000-01-01T00:00:00Z"
            ),
        )
    elif case_id == "V4R-N13":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "readiness_identity",
            lambda value: value["producer"].__setitem__("sha256", "0" * 64),
        )
    elif case_id == "V4R-N14":
        _v4_mutate_event_artifact(
            tmp_path,
            event,
            "receipt_identity",
            lambda value: value["readiness"].__setitem__("sha256", "0" * 64),
        )
    elif case_id == "V4R-N16":
        paths = [
            *context["provider_binding_repair"]["provider_policy"][
                "fixed_provider_map"
            ],
            *context["provider_binding_repair"]["provider_policy"][
                "mutable_provider_paths"
            ],
        ]
        for rel in paths:
            (tmp_path / rel).unlink()
    elif case_id == "V4R-N17":
        for rel in context["provider_binding_repair"]["consumer_map"]:
            (tmp_path / rel).unlink()
    elif case_id == "V4R-N18":
        event["binding_identity"]["provider_map_sha256"] = m.V4_OLD_PROVIDER_MAP_SHA256
    elif case_id == "V4R-N19":
        event["binding_identity"]["provider_map_sha256"] = "f" * 64
    else:
        assert case_id == "V4R-N20"
        source = event["producer_identity"]
        wrong_path = "input/not-derived-producer.json"
        (tmp_path / wrong_path).write_bytes((tmp_path / source["path"]).read_bytes())
        (tmp_path / wrong_path).chmod(0o444)
        event["producer_identity"] = _v4_file_ref(tmp_path, wrong_path)
    _v4_assert_transition_denied(tmp_path, context, event)


# The interruption regressions are intentionally additive to the 346-case
# repair suite.  They exercise only synthetic state and isolated temp roots.
IR_CONTEXT_PATH = (
    ROOT
    / "docs/dev/context-20260816-lane-b-registry-v4-repair-v2-interruption-recovery.json"
)
IR_CONTEXT = json.loads(IR_CONTEXT_PATH.read_text())
IR_CASES = IR_CONTEXT["tests"]["interruption_regression"]["cases"]
assert [case["id"] for case in IR_CASES] == [f"IR-{index:02d}" for index in range(1, 7)]
IR_ADMISSION_PATH = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/cycle-1/"
    "lane-b-registry-v4-repair-v2-interruption-recovery-dev-admission.v1.json"
)
IR_ADMISSION_SHA256 = "6779adef4863d3b43bc2c19f2d204cea1930b0f2e428dd829e023979f7b30018"


def _ir_fixture(root: Path) -> dict:
    source = ROOT / IR_ADMISSION_PATH
    target = root / IR_ADMISSION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    target.chmod(0o444)
    assert _sha(target.read_bytes()) == IR_ADMISSION_SHA256
    workspace = root / "isolated-workspace"
    workspace.mkdir()
    (workspace / "source.py").write_bytes(b"salvageable-partial-source\n")
    (workspace / "test.py").write_bytes(b"unchanged-test-preimage\n")
    return json.loads(target.read_text())


def _ir_observation(admission: dict) -> dict:
    source, test = admission["scope"]["modify_exactly"]
    by_path = {source["path"]: source, test["path"]: test}
    return {
        "before_expiry": True,
        "consumed": False,
        "source_sha256": by_path["scripts/laneb-integration-gate.py"]["sha256"],
        "test_sha256": by_path["hooks/tests/test_laneb_integration_gate.py"]["sha256"],
        "source_inode": by_path["scripts/laneb-integration-gate.py"]["inode"],
        "test_inode": by_path["hooks/tests/test_laneb_integration_gate.py"]["inode"],
        "paths": set(admission["scope"]["allowed_paths"]),
        "fresh_ba_qa_pass": True,
        "fresh_actor": True,
        "open_handles": 0,
        "writable_handles": 0,
        "parent_lock_exact": True,
        "status_exact": True,
        "non_scope_manifest_exact": True,
        "runtime_absent": True,
        "handoff": True,
        "tests_346": True,
        "ir_6": True,
        "black": True,
        "syntax": True,
        "both_paths_changed": True,
    }


def _ir_dispatch_allowed(admission: dict, observed: dict) -> bool:
    source, test = admission["scope"]["modify_exactly"]
    by_path = {source["path"]: source, test["path"]: test}
    return all(
        (
            admission["verdict"] == "PASS",
            observed["before_expiry"],
            not observed["consumed"],
            observed["source_sha256"]
            == by_path["scripts/laneb-integration-gate.py"]["sha256"],
            observed["test_sha256"]
            == by_path["hooks/tests/test_laneb_integration_gate.py"]["sha256"],
            observed["source_inode"]
            == by_path["scripts/laneb-integration-gate.py"]["inode"],
            observed["test_inode"]
            == by_path["hooks/tests/test_laneb_integration_gate.py"]["inode"],
            observed["paths"] == set(admission["scope"]["allowed_paths"]),
            observed["fresh_ba_qa_pass"],
            observed["fresh_actor"],
            observed["open_handles"] == 0,
            observed["writable_handles"] == 0,
            observed["parent_lock_exact"],
            observed["status_exact"],
            observed["non_scope_manifest_exact"],
            observed["runtime_absent"],
        )
    )


def _ir_terminal_pass(admission: dict, observed: dict) -> bool:
    return _ir_dispatch_allowed(admission, observed) and all(
        (
            observed["handoff"],
            observed["tests_346"],
            observed["ir_6"],
            observed["black"],
            observed["syntax"],
            observed["both_paths_changed"],
            admission["freshness_and_release"]["same_agent_terminal_handoff_required"],
        )
    )


@pytest.mark.parametrize(
    "case",
    IR_CASES,
    ids=[case["id"] for case in IR_CASES],
)
def test_registry_v4_interruption_recovery_regression(
    tmp_path: Path, case: dict
) -> None:
    admission = _ir_fixture(tmp_path)
    observed = _ir_observation(admission)
    case_id = case["id"]

    if case_id == "IR-01":
        assert (
            admission["freshness_and_release"]["old_admissions_remaining_authority"]
            == 0
        )
        for drift in (
            {"before_expiry": False},
            {"consumed": True},
            {"source_sha256": "0" * 64},
        ):
            candidate = {**observed, **drift}
            assert _ir_dispatch_allowed(admission, candidate) is False
        return

    if case_id == "IR-02":
        assert _ir_dispatch_allowed(admission, observed) is True
        assert admission["authority_chain"]["independent_BA_QA_verdict"] == "PASS"
        assert admission["required_dispatch_identity"]["call_count_exactly"] == 1
        assert (
            admission["exclusive_ownership"]["active_overlapping_admission_count"] == 0
        )
        return

    workspace = tmp_path / "isolated-workspace"
    source = workspace / "source.py"
    test = workspace / "test.py"
    if case_id == "IR-03":
        source.write_bytes(b"continued-source-before-actor-death\n")
        preserved = source.read_bytes()
        observed["handoff"] = False
        assert _ir_terminal_pass(admission, observed) is False
        assert source.read_bytes() == preserved
        assert test.read_bytes() == b"unchanged-test-preimage\n"
        assert (
            admission["freshness_and_release"][
                "expiry_auto_releases_or_replenishes_call"
            ]
            is False
        )
        return

    if case_id == "IR-04":
        assert admission["partial_source_preservation"][
            "continue_current_partial_source_allowed"
        ]
        assert (
            admission["partial_source_preservation"]["forced_restore_required"] is False
        )
        source.write_bytes(source.read_bytes() + b"continued\n")
        test.write_bytes(test.read_bytes() + b"new-regression\n")
        assert {"source.py", "test.py"} == {path.name for path in workspace.iterdir()}
        assert source.read_bytes().startswith(b"salvageable-partial-source\n")
        return

    if case_id == "IR-05":
        drift_matrix = (
            {"source_sha256": "1" * 64},
            {"source_inode": observed["source_inode"] + 1},
            {"paths": {"scripts/laneb-integration-gate.py"}},
            {"open_handles": 1},
            {"writable_handles": 1},
            {"parent_lock_exact": False},
            {"status_exact": False},
            {"non_scope_manifest_exact": False},
            {"runtime_absent": False},
        )
        before = {path.name: path.read_bytes() for path in workspace.iterdir()}
        for drift in drift_matrix:
            assert _ir_dispatch_allowed(admission, {**observed, **drift}) is False
        assert {path.name: path.read_bytes() for path in workspace.iterdir()} == before
        return

    assert case_id == "IR-06"
    for incomplete in (
        {"handoff": False},
        {"before_expiry": False},
        {"tests_346": False},
        {"ir_6": False},
    ):
        assert _ir_terminal_pass(admission, {**observed, **incomplete}) is False
    assert (
        admission["provider_consumer_order"]["silence_or_missing_handoff_result"]
        != "PASS"
    )


# ---------------------------------------------------------------------------
# Registry-v5 prospective protocol recovery: exactly 50 additive cases.
# ---------------------------------------------------------------------------
V5_CONTEXT_PATH = ROOT / m.V5_CONTEXT_DEFAULT
V5_CONTEXT = json.loads(V5_CONTEXT_PATH.read_text())
V5_CASES = [
    (category, case)
    for category in ("positive", "negative", "concurrency", "crash_recovery", "tamper")
    for case in V5_CONTEXT["test_contract"]["v5_new_logical_cases"][category]
]
assert len(V5_CASES) == 50
assert len({case["id"] for _category, case in V5_CASES}) == 50
assert len({case["name"] for _category, case in V5_CASES}) == 50
assert {
    category: sum(item[0] == category for item in V5_CASES)
    for category in {"positive", "negative", "concurrency", "crash_recovery", "tamper"}
} == {"positive": 8, "negative": 25, "concurrency": 5, "crash_recovery": 6, "tamper": 6}


def _v5_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    target.chmod(stat.S_IMODE(source.stat().st_mode))


def _v5_fixture(root: Path) -> dict:
    context = copy.deepcopy(V5_CONTEXT)
    repair = json.loads((ROOT / m.V4_CONTEXT_DEFAULT).read_text())
    predecessor_ref = repair["authoritative_inputs"]["predecessor_context"]
    predecessor = json.loads((ROOT / predecessor_ref["path"]).read_text())
    v4_context = copy.deepcopy(predecessor)
    v4_context.update(copy.deepcopy(repair))
    copied = {
        m.V5_CONTEXT_DEFAULT,
        m.V5_READINESS_PATH,
        predecessor_ref["path"],
        m.V4_CONTEXT_DEFAULT,
        v4_context["v4_artifacts"]["migration_record"]["path"],
        v4_context["v4_artifacts"]["migration_audit"]["path"],
        v4_context["v4_artifacts"]["registry"]["path"],
        *(
            item["path"]
            for item in context["authoritative_inputs"].values()
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and not Path(item["path"]).is_absolute()
            and item["path"]
            not in {
                "scripts/laneb-integration-gate.py",
                "hooks/tests/test_laneb_integration_gate.py",
            }
        ),
        *(item["path"] for item in predecessor["authoritative_predecessors"].values()),
        *context["provider_consumer_binding"]["fixed_provider_map"],
        *context["provider_consumer_binding"]["consumer_map"],
        *context["provider_consumer_binding"]["mutable_provider_paths"],
    }
    frozen_rows = [
        json.loads(line)
        for line in (ROOT / v4_context["v4_artifacts"]["registry"]["path"])
        .read_text()
        .splitlines()
    ]
    for row in frozen_rows:
        transaction_id = row["transaction_id"]
        for key, template in v4_context["v4_artifacts"][
            "transaction_templates"
        ].items():
            if key != "terminal_failure":
                copied.add(template.replace("{transaction_id}", transaction_id))
    for rel in sorted(copied):
        _v5_copy(ROOT / rel, root / rel)
    for rel in (
        context["v5_artifacts"]["registry"],
        context["v5_artifacts"]["migration_record"],
        context["v5_artifacts"]["migration_audit"],
        context["v5_artifacts"]["activation"],
        context["v5_artifacts"]["lock"],
        *(
            value.replace("{attempt_id}", m.V5_ATTEMPT_ID)
            for value in context["v5_artifacts"]["derived_attempt_paths"].values()
        ),
        *(
            value.replace("{transaction_id}", "0" * 32)
            for value in context["v5_artifacts"]["transaction_templates"].values()
        ),
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
    marker = root / ".laneb-v5-throwaway-root"
    marker.write_bytes(b"LANEB_V5_THROWAWAY\n")
    marker.chmod(0o600)
    lock = root / context["v5_artifacts"]["lock"]
    lock.touch(mode=0o644)
    return context


def _v5_cli(
    root: Path,
    phase: str,
    *args: str,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--project-root",
            str(root),
            "--phase",
            phase,
            "--v5-test-mode",
            *args,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _v5_output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stderr == ""
    assert result.stdout.endswith("\n") and result.stdout.count("\n") == 1
    value = json.loads(result.stdout)
    assert result.stdout.encode() == _canonical(value) + b"\n"
    assert value["G2_provider_satisfied"] is False
    assert value["authorization_effect"] == "none"
    assert value["authorizes"] == []
    return value


def _v5_write(root: Path, rel: str, value: dict, mode: int = 0o444) -> dict:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m._v5_json_line(value))
    path.chmod(mode)
    st = path.stat()
    return {
        "path": rel,
        "bytes": st.st_size,
        "sha256": _sha(path.read_bytes()),
        "mode": f"{stat.S_IMODE(st.st_mode):04o}",
        "nlink": st.st_nlink,
        "state": "file",
        "symlink": False,
    }


def _v5_ref(root: Path, rel: str) -> dict:
    path = root / rel
    data = path.read_bytes()
    st = path.stat()
    return {
        "path": rel,
        "bytes": len(data),
        "sha256": _sha(data),
        "mode": f"{stat.S_IMODE(st.st_mode):04o}",
        "nlink": st.st_nlink,
        "state": "file",
        "symlink": False,
    }


def _v5_commit(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _v5_cli(
        root,
        "registry-v5-migration-commit",
        "--v5-event-at",
        "2026-08-17T23:10:00Z",
        *extra,
    )


def _v5_state(root: Path, context: dict) -> tuple[m.V4File, m.V5Replay, dict, m.V4File]:
    with m.V4Root(root) as safe:
        _cap, loaded = m._v5_context(safe, m.V5_CONTEXT_DEFAULT)
        paths = {
            "v4": context["authoritative_inputs"]["v4_registry"]["path"],
            "registry": context["v5_artifacts"]["registry"],
            "record": context["v5_artifacts"]["migration_record"],
        }
        frozen, _ = m._v5_validate_frozen_v4(
            safe,
            loaded,
            {
                **paths,
                "audit": context["v5_artifacts"]["migration_audit"],
                "activation": context["v5_artifacts"]["activation"],
                "lock": context["v5_artifacts"]["lock"],
                "context": m.V5_CONTEXT_DEFAULT,
            },
        )
        record, _value = m._v5_record(
            safe, loaded, context["v5_artifacts"]["migration_record"], frozen
        )
        registry = safe.read(context["v5_artifacts"]["registry"], modes={0o600})
        assert registry is not None
        replay = m._v5_replay(loaded, registry, record)
        return registry, replay, loaded, record


def _v5_publish_audit(
    root: Path, context: dict, *, agent_id: str = "fresh-v5-migration-qa"
) -> None:
    registry, _replay, loaded, record = _v5_state(root, context)
    frozen_path = context["authoritative_inputs"]["v4_registry"]["path"]
    with m.V4Root(root) as safe:
        frozen = safe.read(frozen_path, modes={0o600})
        assert frozen is not None
        audit = m.v5_expected_migration_audit(
            loaded,
            record,
            registry,
            frozen,
            agent_id,
            "2026-08-17T23:11:00Z",
        )
    _v5_write(root, context["v5_artifacts"]["migration_audit"], audit)


def _v5_activate(root: Path, context: dict) -> None:
    commit = _v5_commit(root)
    assert commit.returncode == 0, commit.stdout
    _v5_publish_audit(root, context)
    activation = _v5_cli(
        root,
        "registry-v5-activate",
        "--v5-event-at",
        "2026-08-17T23:12:00Z",
    )
    assert activation.returncode == 0, activation.stdout


def _v5_allocate(root: Path) -> None:
    result = _v5_cli(
        root,
        "registry-v5-allocate",
        "--v5-event-at",
        "2026-08-17T23:13:00Z",
    )
    assert result.returncode == 0, result.stdout
    assert _v5_output(result)["result"]["attempt_id"] == m.V5_ATTEMPT_ID


def _v5_dispatch(now: dt.datetime, role: str, agent: str, dispatch: str) -> dict:
    return {
        "dispatch_id": dispatch,
        "task_id": "LANE-B-V5-GATE-REPAIR",
        "agent_id": agent,
        "role": role,
        "dispatched_at": (now - dt.timedelta(seconds=31))
        .isoformat()
        .replace("+00:00", "Z"),
        "ticket_sha256": m.V5_TICKET_SHA256,
        "context_sha256": m.V5_CONTEXT_SHA256,
        "ba_qa_sha256": m.V5_BA_QA_SHA256,
        "parent_admission_sha256": m.V5_PARENT_ADMISSION_SHA256,
        "real_dispatch": True,
        "synthetic": False,
        "same_lane": True,
    }


def _v5_event(
    root: Path,
    context: dict,
    event_type: str,
    *,
    now: dt.datetime | None = None,
    salt: str = "0",
    **fields: object,
) -> dict:
    registry, replay, loaded, _record = _v5_state(root, context)
    now = now or dt.datetime.now(dt.timezone.utc)
    event = m.v5_expected_attempt_event(
        loaded,
        registry,
        replay,
        event_type,
        now.isoformat().replace("+00:00", "Z"),
        _sha(f"v5-tx:{event_type}:{len(replay.rows)}:{salt}".encode())[:32],
        _sha(f"v5-nonce:{event_type}:{len(replay.rows)}:{salt}".encode())[:32],
        **fields,
    )
    return event


def _v5_start(root: Path, context: dict, *, dispatch: dict | None = None) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    dispatch = dispatch or _v5_dispatch(
        now, "lane_b_dev", "fresh-v5-dev-agent", "fresh-v5-dev-dispatch"
    )
    event = _v5_event(
        root,
        context,
        "STARTED",
        now=now - dt.timedelta(seconds=30),
        dev_dispatch_identity=dispatch,
    )
    rel = context["v5_artifacts"]["derived_attempt_paths"][
        "started_event_input"
    ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
    _v5_write(root, rel, event)
    result = _v5_cli(
        root,
        "registry-v5-start",
        "--attempt-id",
        m.V5_ATTEMPT_ID,
        "--event-input",
        rel,
    )
    assert result.returncode == 0, result.stdout
    return dispatch


def _v5_evidence(root: Path, context: dict, dev_dispatch: dict) -> tuple[dict, str]:
    now = dt.datetime.now(dt.timezone.utc)
    paths = {
        key: value.replace("{attempt_id}", m.V5_ATTEMPT_ID)
        for key, value in context["v5_artifacts"]["derived_attempt_paths"].items()
    }
    registry, replay, _loaded, _record = _v5_state(root, context)
    started = next(row for row in replay.rows if row.get("event_type") == "STARTED")
    started_sha = _sha(m._v5_json_line(started)[:-1])
    identity = m._v5_attempt_identity()
    implementation = [
        _v5_ref(root, rel)
        for rel in sorted(context["scope_and_ownership"]["allowed_modified_paths"])
    ]
    tests = {"collected": 402, "passed": 402, "failed": 0}
    producer = {
        "schema_name": "lane_b_registry_v5_producer_evidence.v1",
        "schema_version": 1,
        "record_type": "real_dev_producer_evidence",
        "status": "PASS",
        "created_at": (now - dt.timedelta(seconds=5))
        .isoformat()
        .replace("+00:00", "Z"),
        "identity": identity,
        "started_event_sha256": started_sha,
        "dev_dispatch": dev_dispatch,
        "ticket_sha256": m.V5_TICKET_SHA256,
        "context_sha256": m.V5_CONTEXT_SHA256,
        "implementation_files": implementation,
        "changed_paths": sorted(
            context["scope_and_ownership"]["allowed_modified_paths"]
        ),
        "tests": tests,
        "authorization": m._v5_no_authority(),
    }
    producer_ref = _v5_write(root, paths["dev_report"], producer)
    qa_dispatch = _v5_dispatch(
        now, "independent_lane_b_qa", "fresh-v5-qa-agent", "fresh-v5-qa-dispatch"
    )
    qa = {
        "schema_name": "lane_b_registry_v5_independent_qa_evidence.v1",
        "schema_version": 1,
        "record_type": "fresh_independent_implementation_qa",
        "status": "PASS",
        "verdict": "PASS",
        "started_at": (now - dt.timedelta(seconds=4))
        .isoformat()
        .replace("+00:00", "Z"),
        "finalized_at": (now - dt.timedelta(seconds=3))
        .isoformat()
        .replace("+00:00", "Z"),
        "identity": identity,
        "started_event_sha256": started_sha,
        "qa_dispatch": qa_dispatch,
        "qa_agent_id": qa_dispatch["agent_id"],
        "dev_agent_id": dev_dispatch["agent_id"],
        "independent": True,
        "producer": producer_ref,
        "observed_implementation_files": implementation,
        "tests": tests,
        "authorization": m._v5_no_authority(),
    }
    qa_ref = _v5_write(root, paths["qa_report"], qa)
    readiness = {
        "schema_name": "lane_b_registry_v5_consumer_handoff_readiness.v1",
        "schema_version": 1,
        "record_type": "closed_evidence_readiness",
        "status": "READY_FOR_EVIDENCE_SEAL_ONLY",
        "created_at": (now - dt.timedelta(seconds=2))
        .isoformat()
        .replace("+00:00", "Z"),
        "identity": identity,
        "producer": producer_ref,
        "qa": qa_ref,
        "all_inputs_exact": True,
        "authorization": m._v5_no_authority(),
    }
    readiness_ref = _v5_write(root, paths["readiness"], readiness)
    receipt = {
        "schema_name": "lane_b_registry_v5_evidence_repair_receipt.v1",
        "schema_version": 1,
        "record_type": "closed_evidence_receipt",
        "status": "RECEIPT_EXACT_NON_AUTHORIZING",
        "created_at": (now - dt.timedelta(seconds=1))
        .isoformat()
        .replace("+00:00", "Z"),
        "identity": identity,
        "producer": producer_ref,
        "qa": qa_ref,
        "readiness": readiness_ref,
        "authorization": m._v5_no_authority(),
    }
    receipt_ref = _v5_write(root, paths["receipt"], receipt)
    event = _v5_event(
        root,
        context,
        "EVIDENCE_SEALED",
        now=now,
        dev_dispatch_identity=dev_dispatch,
        qa_dispatch_identity=qa_dispatch,
        producer_identity=producer_ref,
        qa_result_identity=qa_ref,
        readiness_identity=readiness_ref,
        receipt_identity=receipt_ref,
    )
    _v5_write(root, paths["evidence_sealed_event_input"], event)
    return event, paths["evidence_sealed_event_input"]


def _v5_ready_for_seal(root: Path, context: dict) -> str:
    _v5_activate(root, context)
    _v5_allocate(root)
    dispatch = _v5_start(root, context)
    _event_value, event_path = _v5_evidence(root, context, dispatch)
    return event_path


def _v5_seal(
    root: Path, context: dict, *extra: str
) -> subprocess.CompletedProcess[str]:
    path = context["v5_artifacts"]["derived_attempt_paths"][
        "evidence_sealed_event_input"
    ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
    return _v5_cli(
        root,
        "registry-v5-seal",
        "--attempt-id",
        m.V5_ATTEMPT_ID,
        "--event-input",
        path,
        *extra,
    )


def _v5_find_intent_tx(root: Path, context: dict, event_type: str) -> str:
    parent = root / Path(context["v5_artifacts"]["registry"]).parent
    matches: list[str] = []
    for path in parent.glob("lane-b-registry-v5-transaction.*.step-01-intent.json"):
        intent = json.loads(path.read_text())
        event = json.loads(bytes.fromhex(intent["intended_event_hex"]))
        if event["event_type"] == event_type:
            matches.append(intent["transaction_id"])
    assert len(matches) == 1, (event_type, matches)
    return matches[0]


def _v5_full(root: Path, context: dict, *, sleep_after_seal: bool = False) -> None:
    _v5_ready_for_seal(root, context)
    sealed = _v5_seal(root, context)
    assert sealed.returncode == 0, sealed.stdout
    if sleep_after_seal:
        time.sleep(4.05)
    promoted = _v5_cli(
        root,
        "registry-v5-promote",
        "--attempt-id",
        m.V5_ATTEMPT_ID,
    )
    assert promoted.returncode == 0, promoted.stdout
    verified = _v5_cli(
        root,
        "verify-h-b-v5-provider-set",
        "--attempt-id",
        m.V5_ATTEMPT_ID,
    )
    assert verified.returncode == 0, verified.stdout
    value = _v5_output(verified)
    assert value["result"]["state"] == "TERMINAL_G2_ELIGIBLE"
    assert value["result"]["G2_reaudit_eligible"] is True


def _v5_assert_oracle(case: dict) -> None:
    oracle = case["persisted_state_oracle"]
    assert oracle["normative_context_path"] == m.V5_CONTEXT_DEFAULT
    assert oracle["normative_context_hash_authority"] == {
        "artifact": m.V5_READINESS_PATH,
        "json_pointer": "/published_BA_artifacts/context/sha256",
    }
    assert oracle["exact_forbidden_persisted_state_values"] == ["ACTIVE"]
    assert oracle["v1_v2_context_normative"] is False
    assert "ACTIVE" not in json.dumps(
        oracle["accepted_persisted_state_after"], ensure_ascii=False
    )


@pytest.mark.parametrize(
    ("category", "case"),
    V5_CASES,
    ids=[f'{case["id"]}-{case["name"]}' for _category, case in V5_CASES],
)
def test_registry_v5_protocol_recovery_case_matrix(
    tmp_path: Path, category: str, case: dict
) -> None:
    _v5_assert_oracle(case)
    case_id = case["id"]
    context = _v5_fixture(tmp_path)

    # Every logical case validates the exact normative schema/state binding;
    # branch-specific E2E below then exercises its positive or denial surface.
    event_schema = context["closed_schemas"]["event"]["schema"]
    assert m.canonical_sha(event_schema) == m.V5_SCHEMA_DIGESTS["event"]
    assert "ACTIVE" not in event_schema["properties"]["persisted_state_after"]["enum"]
    assert context["persisted_state_model"]["closed_vocabulary"] == list(m.V5_STATES)

    if case_id == "V5-P01":
        result = _v5_cli(tmp_path, "registry-v5-migration-preflight")
        assert result.returncode == 0, result.stdout
        assert _v5_output(result)["result"]["source_v4_event_count"] == 8
    elif case_id == "V5-P02":
        result = _v5_commit(tmp_path)
        assert result.returncode == 0, result.stdout
        registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert len(replay.rows) == 1 and registry.data.endswith(b"\n")
    elif case_id == "V5-P03":
        _v5_activate(tmp_path, context)
        assert (tmp_path / context["v5_artifacts"]["activation"]).is_file()
    elif case_id == "V5-P04":
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert replay.allocations == [m.V5_ATTEMPT_ID]
        assert replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)] == "ALLOCATED"
    elif case_id == "V5-P05":
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        _v5_start(tmp_path, context)
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)] == "STARTED"
        assert replay.rows[-1]["persisted_state_after"] == "STARTED"
    elif case_id == "V5-P06":
        _v5_ready_for_seal(tmp_path, context)
        result = _v5_seal(tmp_path, context)
        assert result.returncode == 0, result.stdout
        value = _v5_output(result)["result"]
        assert value["state"] == "EVIDENCE_SEALED"
        assert value["protected_duration_ns"] <= 4_000_000_000
    elif case_id == "V5-P07":
        _v5_full(tmp_path, context)
    elif case_id == "V5-P08":
        _v5_full(tmp_path, context, sleep_after_seal=True)
    elif case_id in {"V5-N01", "V5-N02"}:
        target = tmp_path / context["authoritative_inputs"]["v4_registry"]["path"]
        target.chmod(0o600)
        target.write_bytes(
            target.read_bytes() + (b"{}\n" if case_id == "V5-N02" else b"x")
        )
        result = _v5_cli(tmp_path, "registry-v5-migration-preflight")
        assert result.returncode == 3
        assert not (tmp_path / context["v5_artifacts"]["registry"]).exists()
    elif case_id == "V5-N03":
        target = tmp_path / context["authoritative_inputs"]["binding_denial"]["path"]
        target.chmod(0o644)
        target.write_bytes(target.read_bytes() + b" ")
        target.chmod(0o444)
        assert _v5_cli(tmp_path, "registry-v5-migration-preflight").returncode == 3
    elif case_id == "V5-N04":
        assert _v5_commit(tmp_path).returncode == 0
        assert _v5_cli(tmp_path, "registry-v5-activate").returncode == 2
    elif case_id == "V5-N05":
        assert _v5_commit(tmp_path).returncode == 0
        _v5_publish_audit(tmp_path, context, agent_id="same_spec_parent")
        assert _v5_cli(tmp_path, "registry-v5-activate").returncode == 3
    elif case_id == "V5-N06":
        _v5_activate(tmp_path, context)
        assert _v5_cli(tmp_path, "registry-v5-activate").returncode == 3
    elif case_id in {"V5-N07", "V5-N08"}:
        _v5_activate(tmp_path, context)
        extra = (
            ("--attempt-id", "a000099")
            if case_id == "V5-N07"
            else ("--attempt-kind", "FINAL_FAN_IN")
        )
        assert _v5_cli(tmp_path, "registry-v5-allocate", *extra).returncode == 2
    elif case_id == "V5-N09":
        _v5_activate(tmp_path, context)
        collision = context["v5_artifacts"]["derived_attempt_paths"][
            "dev_report"
        ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
        _v5_write(tmp_path, collision, {"collision": True})
        assert _v5_cli(tmp_path, "registry-v5-allocate").returncode == 3
    elif case_id == "V5-N10":
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        assert _v5_cli(tmp_path, "registry-v5-allocate").returncode == 2
    elif case_id in {"V5-N11", "V5-N12"}:
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        now = dt.datetime.now(dt.timezone.utc)
        dispatch = _v5_dispatch(
            now,
            "lane_b_dev",
            "synthetic-dev" if case_id == "V5-N11" else "old-a000016-dev",
            "synthetic-dispatch" if case_id == "V5-N11" else "old-a000016-dispatch",
        )
        if case_id == "V5-N11":
            dispatch["synthetic"] = True
            dispatch["real_dispatch"] = False
        event = _v5_event(
            tmp_path,
            context,
            "STARTED",
            dev_dispatch_identity=dispatch,
        )
        rel = context["v5_artifacts"]["derived_attempt_paths"][
            "started_event_input"
        ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
        _v5_write(tmp_path, rel, event)
        assert (
            _v5_cli(
                tmp_path,
                "registry-v5-start",
                "--attempt-id",
                m.V5_ATTEMPT_ID,
                "--event-input",
                rel,
            ).returncode
            == 2
        )
    elif case_id in {"V5-N13", "V5-N14"}:
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        dispatch = _v5_start(tmp_path, context)
        _event_value, seal_path = _v5_evidence(tmp_path, context, dispatch)
        if case_id == "V5-N13":
            event = json.loads((tmp_path / seal_path).read_text())
            event["qa_dispatch_identity"]["agent_id"] = dispatch["agent_id"]
            event = m._v5_with_integrity(event)
            _v5_write(tmp_path, seal_path, event, 0o444)
        else:
            producer = context["v5_artifacts"]["derived_attempt_paths"][
                "dev_report"
            ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
            (tmp_path / producer).unlink()
        assert _v5_seal(tmp_path, context).returncode in {2, 3}
    elif case_id == "V5-N15":
        override = "docs/dev/context-20260817-lane-b-registry-v5-stale.json"
        _v5_copy(
            ROOT
            / "docs/dev/context-20260817-lane-b-registry-v5-protocol-recovery.v2.json",
            tmp_path / override,
        )
        assert (
            _v5_cli(
                tmp_path,
                "registry-v5-migration-preflight",
                "--v5-context",
                override,
            ).returncode
            == 2
        )
    elif case_id in {"V5-N16", "V5-N17", "V5-N24"}:
        _v5_activate(tmp_path, context)
        _v5_allocate(tmp_path)
        if case_id == "V5-N24":
            _v5_start(tmp_path, context)
            _registry, replay, loaded, record = _v5_state(tmp_path, context)
            event = _v5_event(tmp_path, context, "TERMINAL_G2_ELIGIBLE")
            with m.V4Root(tmp_path) as safe, pytest.raises(m.GateError):
                m._v5_transition_event(
                    safe,
                    loaded,
                    {
                        "registry": context["v5_artifacts"]["registry"],
                    },
                    record,
                    _registry,
                    replay,
                    event,
                    expected_type="TERMINAL_G2_ELIGIBLE",
                )
        else:
            event = _v5_event(
                tmp_path,
                context,
                "STARTED",
                dev_dispatch_identity=_v5_dispatch(
                    dt.datetime.now(dt.timezone.utc),
                    "lane_b_dev",
                    "fresh-v5-dev-agent",
                    "fresh-v5-dev-dispatch",
                ),
            )
            if case_id == "V5-N16":
                event["attempt_state_before"] = "ACTIVE"
            else:
                event["attempt_state_before"] = "STARTED"
            event = m._v5_with_integrity(event)
            rel = context["v5_artifacts"]["derived_attempt_paths"][
                "started_event_input"
            ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
            _v5_write(tmp_path, rel, event)
            assert (
                _v5_cli(
                    tmp_path,
                    "registry-v5-start",
                    "--attempt-id",
                    m.V5_ATTEMPT_ID,
                    "--event-input",
                    rel,
                ).returncode
                == 2
            )
    elif case_id in {"V5-N18", "V5-N19"}:
        _v5_ready_for_seal(tmp_path, context)
        result = _v5_seal(
            tmp_path,
            context,
            "--v5-test-duration-ns",
            "4000000001",
        )
        assert result.returncode == 0, result.stdout
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert (
            replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)]
            == "TERMINAL_NO_AUTHORITY"
        )
    elif case_id == "V5-N20":
        _v5_ready_for_seal(tmp_path, context)
        crashed = _v5_seal(tmp_path, context, "--v5-crash-after", "append")
        assert crashed.returncode == 5
        tx = _v5_find_intent_tx(tmp_path, context, "EVIDENCE_SEALED")
        recovered = _v5_cli(tmp_path, "registry-v5-recover", "--transaction-id", tx)
        assert recovered.returncode == 0, recovered.stdout
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert (
            replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)]
            == "TERMINAL_NO_AUTHORITY"
        )
    elif case_id in {"V5-N21", "V5-N22", "V5-N23"}:
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context).returncode == 0
        extra: tuple[str, ...] = ()
        if case_id == "V5-N21":
            extra = ("--v5-test-provider-duration-ns", "30000000001")
        else:
            drift_path = (
                "scripts/laneb-integration-gate.py"
                if case_id == "V5-N22"
                else next(iter(context["provider_consumer_binding"]["consumer_map"]))
            )
            target = tmp_path / drift_path
            target.chmod(0o755 if case_id == "V5-N22" else 0o644)
            target.write_bytes(target.read_bytes() + b"\n# drift\n")
        promoted = _v5_cli(
            tmp_path,
            "registry-v5-promote",
            "--attempt-id",
            m.V5_ATTEMPT_ID,
            *extra,
        )
        assert promoted.returncode == 0, promoted.stdout
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert (
            replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)]
            == "TERMINAL_NO_AUTHORITY"
        )
    elif case_id == "V5-N25":
        _v5_full(tmp_path, context)
        assert _v5_cli(tmp_path, "registry-v5-allocate").returncode == 2
    elif case_id == "V5-C01":
        _v5_activate(tmp_path, context)
        barrier = threading.Barrier(2)
        results: list[int] = []

        def contender() -> None:
            barrier.wait()
            results.append(_v5_cli(tmp_path, "registry-v5-allocate").returncode)

        threads = [threading.Thread(target=contender) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results.count(0) == 1
        assert next(code for code in results if code != 0) in {2, 4}
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert replay.allocations == [m.V5_ATTEMPT_ID]
    elif case_id == "V5-C02":
        _v5_ready_for_seal(tmp_path, context)
        first = _v5_seal(tmp_path, context)
        second = _v5_seal(tmp_path, context)
        assert first.returncode == second.returncode == 0
        assert _v5_output(second)["result"]["result"] == "ALREADY_EVIDENCE_SEALED_EXACT"
    elif case_id == "V5-C03":
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context).returncode == 0
        barrier = threading.Barrier(2)
        results: list[int] = []

        def promote() -> None:
            barrier.wait()
            results.append(
                _v5_cli(
                    tmp_path,
                    "registry-v5-promote",
                    "--attempt-id",
                    m.V5_ATTEMPT_ID,
                ).returncode
            )

        threads = [threading.Thread(target=promote) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results.count(0) in {1, 2}
        assert set(results) <= {0, 4}
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert sum(row["event_type"] == "PROVIDER_VERIFIED" for row in replay.rows) == 1
        assert (
            sum(row["event_type"] == "TERMINAL_G2_ELIGIBLE" for row in replay.rows) == 1
        )
    elif case_id == "V5-C04":
        lock = tmp_path / context["v5_artifacts"]["lock"]
        with lock.open("r+") as handle:
            import fcntl as _fcntl

            _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            result = _v5_cli(
                tmp_path,
                "registry-v5-migration-commit",
                "--lock-timeout",
                "0",
            )
        assert result.returncode == 4
    elif case_id == "V5-C05":
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context).returncode == 0
        target = tmp_path / "scripts/laneb-integration-gate.py"
        target.write_bytes(target.read_bytes() + b"\n# concurrent drift\n")
        result = _v5_cli(
            tmp_path,
            "registry-v5-promote",
            "--attempt-id",
            m.V5_ATTEMPT_ID,
        )
        assert result.returncode == 0
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert (
            replay.states[(m.V5_ATTEMPT_KIND, m.V5_ATTEMPT_ID)]
            == "TERMINAL_NO_AUTHORITY"
        )
    elif case_id == "V5-R01":
        crashed = _v5_commit(tmp_path, "--v5-crash-after", "migration-record")
        assert crashed.returncode == 5
        assert _v5_commit(tmp_path).returncode == 0
    elif case_id == "V5-R02":
        crashed = _v5_commit(tmp_path, "--v5-crash-after", "partial")
        assert crashed.returncode == 5
        record = json.loads(
            (tmp_path / context["v5_artifacts"]["migration_record"]).read_text()
        )
        tx = _sha(
            (
                "v5-genesis-transaction:"
                + _sha(
                    (
                        tmp_path / context["v5_artifacts"]["migration_record"]
                    ).read_bytes()
                )
            ).encode()
        )[:32]
        assert (
            _v5_cli(tmp_path, "registry-v5-recover", "--transaction-id", tx).returncode
            == 0
        )
        assert record["status"] == "V5_INACTIVE_PENDING_INDEPENDENT_AUDIT"
    elif case_id == "V5-R03":
        _v5_activate(tmp_path, context)
        crashed = _v5_cli(
            tmp_path,
            "registry-v5-allocate",
            "--v5-crash-after",
            "partial",
        )
        assert crashed.returncode == 5
        tx = _v5_find_intent_tx(tmp_path, context, "ALLOCATED")
        assert (
            _v5_cli(tmp_path, "registry-v5-recover", "--transaction-id", tx).returncode
            == 0
        )
    elif case_id == "V5-R04":
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context, "--v5-crash-after", "append").returncode == 5
        tx = _v5_find_intent_tx(tmp_path, context, "EVIDENCE_SEALED")
        assert (
            _v5_cli(tmp_path, "registry-v5-recover", "--transaction-id", tx).returncode
            == 0
        )
        _registry, replay, _loaded, _record = _v5_state(tmp_path, context)
        assert replay.rows[-2]["persisted_state_after"] == "EVIDENCE_SEALED"
        assert replay.rows[-1]["persisted_state_after"] == "TERMINAL_NO_AUTHORITY"
    elif case_id == "V5-R05":
        _v5_ready_for_seal(tmp_path, context)
        crashed = _v5_seal(tmp_path, context, "--v5-crash-after", "timing-receipt")
        assert crashed.returncode == 5
        assert _v5_seal(tmp_path, context).returncode == 0
    elif case_id == "V5-R06":
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context).returncode == 0
        crashed = _v5_cli(
            tmp_path,
            "registry-v5-promote",
            "--attempt-id",
            m.V5_ATTEMPT_ID,
            "--v5-crash-after",
            "provider-append",
        )
        assert crashed.returncode == 5
        tx = _v5_find_intent_tx(tmp_path, context, "PROVIDER_VERIFIED")
        assert (
            _v5_cli(tmp_path, "registry-v5-recover", "--transaction-id", tx).returncode
            == 0
        )
        assert (
            _v5_cli(
                tmp_path,
                "registry-v5-promote",
                "--attempt-id",
                m.V5_ATTEMPT_ID,
            ).returncode
            == 0
        )
    elif case_id in {"V5-T01", "V5-T02", "V5-T03"}:
        _v5_activate(tmp_path, context)
        target = (
            tmp_path / context["v5_artifacts"]["registry"]
            if case_id == "V5-T01"
            else (
                tmp_path / context["v5_artifacts"]["activation"]
                if case_id == "V5-T03"
                else sorted(
                    (tmp_path / Path(context["v5_artifacts"]["registry"]).parent).glob(
                        "lane-b-registry-v5-transaction.*.step-03-commit.json"
                    )
                )[0]
            )
        )
        target.chmod(0o644)
        target.write_bytes(target.read_bytes() + b" ")
        if case_id != "V5-T01":
            target.chmod(0o444)
        assert _v5_cli(tmp_path, "registry-v5-allocate").returncode in {2, 3, 5}
    elif case_id == "V5-T04":
        _v5_ready_for_seal(tmp_path, context)
        assert _v5_seal(tmp_path, context).returncode == 0
        path = context["v5_artifacts"]["derived_attempt_paths"][
            "timing_receipt"
        ].replace("{attempt_id}", m.V5_ATTEMPT_ID)
        value = json.loads((tmp_path / path).read_text())
        value["duration_ns"] += 1
        (tmp_path / path).chmod(0o644)
        _v5_write(tmp_path, path, value)
        assert (
            _v5_cli(
                tmp_path,
                "registry-v5-promote",
                "--attempt-id",
                m.V5_ATTEMPT_ID,
            ).returncode
            == 3
        )
    elif case_id in {"V5-T05", "V5-T06"}:
        _v5_full(tmp_path, context)
        key = "provider_verification" if case_id == "V5-T05" else "terminal_marker"
        path = context["v5_artifacts"]["derived_attempt_paths"][key].replace(
            "{attempt_id}", m.V5_ATTEMPT_ID
        )
        target = tmp_path / path
        target.chmod(0o644)
        target.write_bytes(target.read_bytes() + b" ")
        target.chmod(0o444)
        assert (
            _v5_cli(
                tmp_path,
                "verify-h-b-v5-provider-set",
                "--attempt-id",
                m.V5_ATTEMPT_ID,
            ).returncode
            == 3
        )
    else:  # pragma: no cover - the immutable context is a closed 50-case set
        raise AssertionError(f"unhandled v5 case: {category}/{case_id}")
