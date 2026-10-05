#!/usr/bin/env python3
"""Tests for scripts/close-commit-repair-orchestrate.py (ticket-20260930-132644-l8 Part B).

Covers AC-L8-05..08 and AC-L8-14..16
(docs/dev/acceptance-criteria-20260930-132644-l8.json). Every test supplies
its own stub dispatch_fn/rerun_fn/instrument_probe_fn/restart_lane_fn --
production side-effecting calls are never exercised here (AC7: no file
write from the engine itself; only Agent-dispatch and recheck-command calls,
both of which are these very stubs).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "close-commit-repair-orchestrate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("close_commit_repair_orchestrate", ENGINE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = _load_module()


def _never_dispatch(*_args, **_kwargs):
    raise AssertionError("dispatch_fn must not be called for this test")


def _never_rerun(*_args, **_kwargs):
    raise AssertionError("rerun_fn must not be called for this test")


def _never_probe(*_args, **_kwargs):
    raise AssertionError("instrument_probe_fn must not be called for this test")


def _never_restart(*_args, **_kwargs):
    raise AssertionError("restart_lane_fn must not be called for this test")


def _run(findings, table, **overrides):
    kwargs = dict(
        dispatch_fn=_never_dispatch, rerun_fn=_never_rerun,
        instrument_probe_fn=_never_probe, restart_lane_fn=_never_restart,
    )
    kwargs.update(overrides)
    return ENGINE.run_engine(findings, table, **kwargs)


# ---------------------------------------------------------------------------
# AC-L8-05: happy path
# ---------------------------------------------------------------------------

def test_AC_L8_05_happy_path_first_attempt_dispatch():
    table = {"close#1": {"code": "close#1", "action": "dispatch_producer_fix", "producer_role": "dev"}}
    findings = [{"code": "close#1", "path": "docs/dev/x.json", "detail": "missing"}]
    dispatch = mock.Mock(return_value={"status": "success"})
    result = _run(findings, table, dispatch_fn=dispatch)
    assert result == {"continue": True, "disclosures": []}
    assert dispatch.call_count == 1


def test_AC_L8_05_happy_path_second_attempt_rerun():
    table = {"close#13": {"code": "close#13", "action": "rerun_tool", "producer_role": None}}
    findings = [{"code": "close#13", "path": "docs/dev/dev-report-20260101-000000.json", "detail": "stale"}]
    rerun = mock.Mock(side_effect=[False, True])
    result = _run(findings, table, rerun_fn=rerun)
    assert result == {"continue": True, "disclosures": []}
    assert rerun.call_count == 2


# ---------------------------------------------------------------------------
# AC-L8-06: retry ceiling + terminal split (land_with_disclosure vs stall)
# ---------------------------------------------------------------------------

def test_AC_L8_06_dispatch_exhausted_lands_with_disclosure():
    table = {"close#56": {"code": "close#56", "action": "dispatch_producer_fix", "producer_role": None}}
    findings = [{"code": "close#56", "path": "p", "detail": "d"}]
    dispatch = mock.Mock(return_value={"status": "error", "detail": "still failing"})
    result = _run(findings, table, dispatch_fn=dispatch)
    assert dispatch.call_count == ENGINE.MAX_ATTEMPTS
    assert result["continue"] is True
    assert "output" not in result
    assert len(result["disclosures"]) == 1
    disclosure = result["disclosures"][0]
    for key in ("code", "path", "detail", "producer_role", "action"):
        assert key in disclosure


def test_AC_L8_06_s_bucket_exhausted_stalls_and_is_the_only_continue_false():
    table = {
        "close#34": {"code": "close#34", "action": "retry_then_stall", "producer_role": None},
        "close#56": {"code": "close#56", "action": "dispatch_producer_fix", "producer_role": None},
    }
    findings = [{"code": "close#34", "path": "p", "detail": "instrument down"}]
    probe = mock.Mock(return_value=False)
    result = _run(findings, table, instrument_probe_fn=probe)
    assert probe.call_count == ENGINE.MAX_ATTEMPTS
    assert result["continue"] is False
    assert result["output"] == "OPERATION_STALLED"

    # A land_with_disclosure-exhausted finding alone never sets continue:false.
    findings_disclosure_only = [{"code": "close#56", "path": "p", "detail": "d"}]
    result2 = _run(findings_disclosure_only, table, dispatch_fn=lambda *a, **k: {"status": "error"})
    assert result2["continue"] is True


# ---------------------------------------------------------------------------
# AC-L8-07: engine never writes a file
# ---------------------------------------------------------------------------

def test_AC_L8_07_engine_never_writes_a_file(tmp_path, monkeypatch):
    table = {
        "close#56": {"code": "close#56", "action": "land_with_disclosure", "producer_role": None},
        "close#44": {"code": "close#44", "action": "dispatch_producer_fix", "producer_role": "ba"},
        "close#13": {"code": "close#13", "action": "rerun_tool", "producer_role": None},
    }
    findings = [
        {"code": "close#56", "path": "p1", "detail": "d1"},
        {"code": "close#44", "path": "p2", "detail": "d2"},
        {"code": "close#13", "path": "p3", "detail": "d3"},
    ]

    def _no_write(*_args, **_kwargs):
        raise AssertionError("engine must never write a file directly")

    monkeypatch.setattr(Path, "write_text", _no_write, raising=True)
    monkeypatch.setattr(Path, "write_bytes", _no_write, raising=True)

    result = _run(
        findings, table,
        dispatch_fn=lambda *a, **k: {"status": "success"},
        rerun_fn=lambda *a, **k: True,
    )
    assert result["continue"] is True


# ---------------------------------------------------------------------------
# AC-L8-08: internal exception degrades safely
# ---------------------------------------------------------------------------

def test_AC_L8_08_malformed_table_entry_degrades_to_disclosure():
    # Entry missing the required "action" key -- table[code]["action"] raises
    # KeyError inside _process_one_finding.
    table = {"close#1": {"code": "close#1", "producer_role": "dev"}}
    findings = [{"code": "close#1", "path": "p", "detail": "d"}]
    result = _run(findings, table)
    assert result["continue"] is True
    assert isinstance(result["disclosures"], list)
    assert len(result["disclosures"]) == 1
    assert "internal engine error" in result["disclosures"][0]["detail"]


def test_AC_L8_08_non_dict_finding_degrades_to_disclosure_not_crash():
    table = {}
    findings = ["not-a-dict-finding"]
    result = _run(findings, table)
    assert result["continue"] is True
    assert len(result["disclosures"]) == 1


# ---------------------------------------------------------------------------
# AC-L8-14: rerun_tool path distinct from dispatch_producer_fix
# ---------------------------------------------------------------------------

def test_AC_L8_14_rerun_tool_path_never_calls_dispatch():
    table = {"close#13": {"code": "close#13", "action": "rerun_tool", "producer_role": None}}
    findings = [{"code": "close#13", "path": "docs/dev/dev-report-20260101-000000.json", "detail": "deleted"}]
    rerun = mock.Mock(return_value=True)
    result = _run(findings, table, rerun_fn=rerun)
    assert result == {"continue": True, "disclosures": []}
    rerun.assert_called_once_with("close#13", "docs/dev/dev-report-20260101-000000.json")


# ---------------------------------------------------------------------------
# AC-L8-15: restart_lane sentinel path
# ---------------------------------------------------------------------------

def test_AC_L8_15_restart_lane_success():
    findings = [{"code": "lane_incomplete", "path": "r05", "detail": "shard non-terminal"}]
    restart = mock.Mock(return_value=True)
    result = _run(findings, {}, restart_lane_fn=restart)
    assert result == {"continue": True, "disclosures": []}


def test_AC_L8_15_restart_lane_exhausted_discloses_lane_incomplete():
    findings = [{"code": "lane_incomplete", "path": "r05", "detail": "shard non-terminal"}]
    restart = mock.Mock(return_value=False)
    result = _run(findings, {}, restart_lane_fn=restart)
    assert restart.call_count == ENGINE.MAX_ATTEMPTS
    assert result["continue"] is True
    assert len(result["disclosures"]) == 1
    detail = result["disclosures"][0]["detail"]
    assert "r05" in detail
    assert "未完成" in detail
    assert result["disclosures"][0]["action"] == "restart_lane"


# ---------------------------------------------------------------------------
# AC-L8-16: repair-denied-by-whitelist path
# ---------------------------------------------------------------------------

def test_AC_L8_16_whitelist_denial_not_retried_lands_with_hook_text():
    table = {"close#44": {"code": "close#44", "action": "dispatch_producer_fix", "producer_role": "ba"}}
    findings = [{"code": "close#44", "path": "/outside/whitelist/evil.py", "detail": "fix it"}]
    denial_text = "BLOCKED: path /outside/whitelist/evil.py is outside role 'ba' whitelist"
    dispatch = mock.Mock(return_value={"status": "denied", "detail": denial_text})
    result = _run(findings, table, dispatch_fn=dispatch)
    assert dispatch.call_count == 1, "a denial must not be retried as a transient failure"
    assert result["continue"] is True
    assert len(result["disclosures"]) == 1
    disclosure = result["disclosures"][0]
    assert disclosure["detail"] == denial_text
    assert disclosure["action"] == "dispatch_producer_fix"


# ---------------------------------------------------------------------------
# Table loading sanity (against the real generated table).
# ---------------------------------------------------------------------------

def test_load_table_real_file_indexes_by_code():
    table = ENGINE.load_table()
    assert len(table) == 474
    assert table["close#44"]["bucket"] == "P"
    assert table["commit#88"]["note"] == "partial_a"
