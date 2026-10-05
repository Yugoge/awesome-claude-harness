"""Standalone tests for hooks/lib/progress_measure.py (lane L13, R15).

Only throwaway directories are used; the helper is imported by file path so
no gate or registry is involved.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parent.parent / "lib" / "progress_measure.py"


@pytest.fixture()
def pm():
    spec = importlib.util.spec_from_file_location("progress_measure_under_test", _HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rounds(pm, path, steps, loop="loop"):
    return [pm.record_round(str(path), loop, fp, found)["outcome"] for found, fp in steps]


def test_finding_key_is_order_duplicate_and_spelling_insensitive(pm):
    a = pm.finding_id("X", "/p/docs/a.md", "/p")
    assert a == pm.finding_id("X", "docs/a.md") == "X|docs/a.md"
    b = "Y|docs/b.md"
    assert pm.finding_key([a, b], "s") == pm.finding_key([b, a, b], "s")
    assert pm.finding_key([a], "s") != pm.finding_key([a], "t")


def test_world_fingerprint_pins_explicit_paths_only(pm, tmp_path):
    (tmp_path / "a").write_text("1")
    fp = pm.world_fingerprint(str(tmp_path), ["a", "gone"])
    (tmp_path / "other").write_text("x")
    assert pm.world_fingerprint(str(tmp_path), ["gone", "a"]) == fp
    (tmp_path / "a").write_text("2")
    assert pm.world_fingerprint(str(tmp_path), ["a", "gone"]) != fp


def test_progress_rule_and_no_reset(pm, tmp_path):
    A, B = "A", "B"
    assert _rounds(pm, tmp_path / "1.json", [([A], "f"), ([B], "f"), ([A], "f")]) == [
        "first", "no_progress", "no_progress"]
    assert _rounds(pm, tmp_path / "2.json",
                   [([A, B], "f"), ([A], "f"), ([A, B], "f"), ([A], "f")]) == [
        "first", "progress", "no_progress", "no_progress"]
    assert _rounds(pm, tmp_path / "3.json", [([A], "f1"), ([A], "f2"), ([A], "f1")]) == [
        "first", "progress", "no_progress"]
    assert pm.read_state(str(tmp_path / "2.json"))["round"] == 4


def test_no_progress_enters_arbitration_then_awaiting_records_emissions(pm, tmp_path):
    path = str(tmp_path / "s.json")
    pm.record_round(path, "loop", "f", ["A"])
    second = pm.record_round(path, "loop", "f", ["A"])
    assert (second["outcome"], second["phase"]) == ("no_progress", "arbitration")
    key = pm.finding_key(["A"], "loop")
    verdict = {"verdict": "awaiting_input", "finding_key": key, "need": "n", "why": "w", "for": "user"}
    audit = tmp_path / "audit.jsonl"
    ok, reason = pm.declare_awaiting_input(path, "loop", verdict, key, audit_path=str(audit))
    assert ok, reason
    emissions = pm.read_state(path)["awaiting"]["emissions"]
    third = pm.record_round(path, "loop", "f", ["A"])
    assert third["phase"] == "awaiting_input"
    state = pm.read_state(path)
    assert state["awaiting"]["emissions"] == emissions + 1 and state["awaiting"]["last_emitted_at"]
    back = pm.record_round(path, "loop", "changed", ["A"])
    assert (back["outcome"], back["phase"]) == ("progress", "block")


@pytest.mark.parametrize("override,reason", [
    ({"need": ""}, "need_or_why_missing"),
    ({"why": "n"}, "need_equals_why"),
    ({"for": "agent"}, "for_not_user_or_operator"),
    ({"finding_key": "0" * 16}, "finding_key_mismatch"),
])
def test_invalid_verdicts_rejected_and_audited_once(pm, tmp_path, override, reason):
    path = str(tmp_path / "s.json")
    pm.record_round(path, "loop", "f", ["A"])
    pm.record_round(path, "loop", "f", ["A"])
    key = pm.finding_key(["A"], "loop")
    verdict = {"verdict": "awaiting_input", "finding_key": key, "need": "n", "why": "w", "for": "user"}
    verdict.update(override)
    audit = tmp_path / "audit.jsonl"
    for _ in range(2):
        ok, got = pm.declare_awaiting_input(path, "loop", verdict, key, audit_path=str(audit))
        assert (ok, got) == (False, reason)
    assert pm.read_state(path)["phase"] == "arbitration"
    assert len(audit.read_text().splitlines()) == 1


def test_block_phase_rejects_declaration(pm, tmp_path):
    path = str(tmp_path / "s.json")
    pm.record_round(path, "loop", "f", ["A"])
    key = pm.finding_key(["A"], "loop")
    verdict = {"verdict": "awaiting_input", "finding_key": key, "need": "n", "why": "w", "for": "user"}
    assert pm.declare_awaiting_input(path, "loop", verdict, key) == (False, "phase_not_arbitration")


def test_corrupt_and_foreign_state_is_no_prior_round(pm, tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{garbage")
    assert pm.record_round(str(path), "loop", "f", ["A"])["outcome"] == "first"
    foreign = pm.record_round(str(path), "other-loop", "f", ["A"])
    assert foreign["outcome"] == "first" and foreign["round"] == 1


def test_unwritable_is_awaiting_input_never_allow_and_never_raises(pm, tmp_path, monkeypatch):
    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(pm, "_write_atomic", boom)
    rnd = pm.record_round(str(tmp_path / "a.json"), "loop", "f", ["A"],
                          fallback_path=str(tmp_path / "b.json"))
    assert rnd["outcome"] == "unwritable" and rnd["phase"] == "awaiting_input"
    assert "a.json" in rnd["reason"] and "b.json" in rnd["reason"]


def test_fallback_path_used_when_primary_fails(pm, tmp_path, monkeypatch):
    real = pm._write_atomic

    def only_fallback(path, text):
        if str(path).endswith("primary.json"):
            raise OSError("ro")
        return real(path, text)

    monkeypatch.setattr(pm, "_write_atomic", only_fallback)
    fb = tmp_path / "fallback.json"
    rnd = pm.record_round(str(tmp_path / "primary.json"), "loop", "f", ["A"], fallback_path=str(fb))
    assert rnd["outcome"] == "first" and rnd["state_path"] == str(fb)
    again = pm.record_round(str(tmp_path / "primary.json"), "loop", "f", ["A"], fallback_path=str(fb))
    assert again["outcome"] == "no_progress" and again["round"] == 2


def test_enums_have_no_allow_value(pm):
    assert pm.OUTCOMES == ("first", "progress", "no_progress", "unwritable")
    assert pm.PHASES == ("block", "arbitration", "awaiting_input")
    json.dumps(pm.OUTCOMES + pm.PHASES)
