"""A declared artifact's presence and JSON reading has one place: overnight.read_declared_json.

The cycle counter, the closeout reader, the contract library's obligation validation and the
artifact chain's JSON reader ask it and keep their own verdicts; none of them tests the file itself.
A cycle's completeness is overnight.cycle_complete, asked by the counter and the closeout reader.
"""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
REPO = HOOKS.parent
sys.path.insert(0, str(REPO))

overnight = importlib.import_module("hooks.lib.overnight")
contract_runtime = importlib.import_module("hooks.lib.contract_runtime")

_spec = importlib.util.spec_from_file_location("chain_under_test", REPO / "scripts" / "resolve-dev-artifact-chain.py")
chain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chain)


@pytest.fixture
def asked(monkeypatch):
    """The paths the one place was asked about."""
    seen = []
    real = overnight.read_declared_json

    def spy(path):
        seen.append(Path(path))
        return real(path)

    monkeypatch.setattr(overnight, "read_declared_json", spy)
    return seen


def _state(tmp_path):
    return {"session_id": "s1", "worktree_path": str(tmp_path)}


def test_the_reading_names_each_state_of_the_file(tmp_path):
    p = tmp_path / "a.json"
    assert overnight.read_declared_json(p).status == "absent"
    p.write_text("   ")
    assert overnight.read_declared_json(p).status == "empty"
    p.write_text("{")
    assert overnight.read_declared_json(p).status == "malformed"
    p.write_bytes(b"\xff\xfe")
    assert overnight.read_declared_json(p).status == "unreadable"
    p.write_text('{"a": 1}')
    r = overnight.read_declared_json(p)
    assert (r.status, r.value, r.is_file) == ("ok", {"a": 1}, True)
    d = tmp_path / "dir.json"
    d.mkdir()
    r = overnight.read_declared_json(d)
    assert r.exists and not r.is_file and r.status == "unreadable"


def test_the_cycle_counter_asks_the_one_place_and_counts_as_before(tmp_path, asked):
    base = overnight.session_dir(_state(tmp_path))
    base.mkdir(parents=True)
    (base / "retro-report-cycle1.json").write_text("not json at all")  # presence counts, as before
    assert overnight.cycle_index(_state(tmp_path)) == 2
    assert base / "retro-report-cycle1.json" in asked and base / "retro-report-cycle2.json" in asked


def test_the_closeout_reader_asks_the_one_place(tmp_path, asked):
    base = overnight.session_dir(_state(tmp_path))
    base.mkdir(parents=True)
    (base / "retro-report-cycle1.json").write_text("{}")
    gaps = overnight.closeout_gaps(_state(tmp_path), tmp_path)
    assert not any("retrospective" in g for g in gaps)
    assert base / "retro-report-cycle1.json" in asked


def test_the_obligation_validation_asks_the_one_place(tmp_path, asked):
    p = tmp_path / "x.json"
    assert contract_runtime.validate_artifact_for_obligation(p, "retro-report.v1")["status"] == "fail"
    p.write_text("{")
    r = contract_runtime.validate_artifact_for_obligation(p, "retro-report.v1")
    assert r["status"] == "fail" and r["errors"][0].startswith("unparseable JSON: ")
    assert asked == [p, p]


def test_the_chain_reader_asks_the_one_place_and_names_the_same_codes(tmp_path, asked):
    v = chain.ChainValidator(tmp_path, "t")
    q = tmp_path / "qa-report-t.json"
    assert v.read_json(q) is None
    q.write_text("")
    assert v.read_json(q) is None
    q.write_text("[1]")
    assert v.read_json(q) is None
    q.write_text("{")
    assert v.read_json(q) is None
    q.write_text('{"status": "pass"}')
    assert v.read_json(q) == {"status": "pass"}
    assert [e["code"] for e in v.errors] == ["MISSING_ARTIFACT", "EMPTY_ARTIFACT", "INVALID_JSON_TYPE", "MALFORMED_JSON"]
    assert asked == [q] * 5


def test_a_declared_artifact_that_is_not_utf8_is_a_plain_fail_at_each_reader_that_reads(tmp_path, asked):
    """Before the one place, the bytes were decoded in the reader and the decode error escaped it."""
    p = tmp_path / "qa-report-t.json"
    p.write_bytes(b'{"a": "\xff\xfe"}')
    r = contract_runtime.validate_artifact_for_obligation(p, "retro-report.v1")
    assert r["status"] == "fail" and r["errors"][0].startswith("unparseable JSON: ")
    v = chain.ChainValidator(tmp_path, "t")
    assert v.read_json(p) is None
    assert [e["code"] for e in v.errors] == ["UNREADABLE_ARTIFACT"]
    assert asked == [p, p]


def test_the_counter_and_the_closeout_reader_do_not_raise_on_a_file_that_is_not_utf8(tmp_path):
    base = overnight.session_dir(_state(tmp_path))
    base.mkdir(parents=True)
    (base / "retro-report-cycle1.json").write_bytes(b"\xff\xfe")  # presence only: counted, never decoded for a verdict
    assert overnight.cycle_index(_state(tmp_path)) == 2
    assert not any("retrospective" in g for g in overnight.closeout_gaps(_state(tmp_path), tmp_path))


def test_the_counter_and_the_closeout_reader_ask_the_one_place_for_a_complete_cycle(tmp_path, monkeypatch):
    """"Is this cycle complete" is said once (overnight.cycle_complete); both readers ask it and keep their verdicts."""
    base = overnight.session_dir(_state(tmp_path))
    base.mkdir(parents=True)
    seen = []
    real = overnight.cycle_complete

    def spy(b, cycle):
        seen.append((Path(b), str(cycle)))
        return real(b, cycle)

    monkeypatch.setattr(overnight, "cycle_complete", spy)
    no_report = lambda: any("retrospective" in g for g in overnight.closeout_gaps(_state(tmp_path), tmp_path))
    assert overnight.cycle_index(_state(tmp_path)) == 1 and no_report()      # no cycle yet
    assert seen == [(base, "1")]
    (base / "retro-report-cycle3.json").write_text("{}")                      # a gap in the numbering
    seen.clear()
    assert overnight.cycle_index(_state(tmp_path)) == 1 and not no_report()
    assert seen == [(base, "1"), (base, "3")]
    (base / "retro-report-cycle1.json").write_bytes(b"\xff\xfe")              # unreadable: complete, as before
    assert overnight.cycle_index(_state(tmp_path)) == 2
