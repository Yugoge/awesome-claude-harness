"""The time of a dispatch is the CLI's record of the event the dispatch gate handled.

The orchestrator types no time: the dispatch gate (hooks/pretool-obligation-gate.py) accepts an
obligation block without ``dispatched_at`` and one whose typed value is old, and every reader of
a dispatch's time takes the timestamp the CLI wrote on the transcript record of that dispatch's
own tool use (obligation.dispatch_time), never the typed value. What the five-minute bound used
to protect (a block copied from an earlier dispatch, whose old time would make the earlier
round's files look written for this dispatch) is refused at the producer's stop instead.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from lib import command_span, obligation  # noqa: E402

import test_obligation_gate as gate  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ace = _load("test_artifact_contract_enforce")

RECORDED = "2026-11-20T10:00:00.250Z"
OLD = "2026-11-20T07:00:00Z"  # three hours before the record


def _z(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# -- the gate ---------------------------------------------------------------------------


def _gate_in_dev_span(tmp_path, doc):
    home, project = gate._dirs(tmp_path)
    payload = gate._dispatch_payload(tmp_path, gate._unique_sid("time"), gate._span_records("dev"),
                                     subagent_type="ba", prompt="do work\n" + gate._block(doc))
    return gate._run_hook(home, project, payload, switch="block")


def test_a_block_without_a_time_is_accepted(tmp_path):
    doc = gate._obligation_doc(role="ba")
    del doc["dispatched_at"]
    run = _gate_in_dev_span(tmp_path, doc)
    assert run.returncode == 0, run.stderr
    assert isinstance(obligation.parse_obligation(gate._block(doc)), obligation.ParsedObligation)


def test_an_old_typed_time_is_no_reason_to_refuse(tmp_path):
    run = _gate_in_dev_span(tmp_path, gate._obligation_doc(role="ba", dispatched_at=OLD))
    assert run.returncode == 0, run.stderr


def test_an_unreadable_typed_time_is_no_reason_to_refuse(tmp_path):
    run = _gate_in_dev_span(tmp_path, gate._obligation_doc(role="ba", dispatched_at="right now"))
    assert run.returncode == 0, run.stderr


# -- the readers ------------------------------------------------------------------------


def _session(tmp_path, typed=OLD, recorded=RECORDED, ident="toolu_dispatch_time"):
    """A session transcript whose one dispatch the CLI recorded at ``recorded``."""
    doc = gate._obligation_doc(role="dev")
    if typed is None:
        del doc["dispatched_at"]
    else:
        doc["dispatched_at"] = typed
    use = gate._tool_use(ident, "Agent", {"subagent_type": "dev", "prompt": "do work\n" + gate._block(doc)})
    if recorded is not None:
        use["timestamp"] = recorded
    transcript = tmp_path / "session.jsonl"
    records = gate._span_records("dev") + [use]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return transcript, ident


def test_the_dispatch_records_carry_the_record_time(tmp_path):
    for typed in (OLD, None):
        transcript, _ident = _session(tmp_path, typed=typed)
        (record,) = obligation.dispatch_obligations(transcript)
        assert record["obligation"]["dispatched_at"] == RECORDED, typed


def test_a_span_s_dispatches_carry_the_record_time(tmp_path):
    for typed in (OLD, None):
        transcript, _ident = _session(tmp_path, typed=typed)
        (_call, doc), = command_span.active_span(transcript).dispatches()
        assert doc["dispatched_at"] == RECORDED, typed


def test_a_reader_handed_the_event_reads_the_record_time(tmp_path):
    """The PostToolUse readers (the overnight file check, the dev-loop guard check) hold the
    dispatch's tool_use_id and its prompt's obligation."""
    transcript, ident = _session(tmp_path)
    doc = gate._obligation_doc(role="dev", dispatched_at=OLD)
    assert obligation.recorded_dispatch(doc, transcript, ident)["dispatched_at"] == RECORDED
    assert obligation.recorded_dispatch(doc, None, ident) == doc


def test_without_a_record_time_the_typed_value_stands_and_none_is_none(tmp_path):
    transcript, _ident = _session(tmp_path, recorded=None)
    (record,) = obligation.dispatch_obligations(transcript)
    assert record["obligation"]["dispatched_at"] == OLD
    transcript, _ident = _session(tmp_path, typed=None, recorded=None)
    (record,) = obligation.dispatch_obligations(transcript)
    assert "dispatched_at" not in record["obligation"]


def _parent(s, prompt: str, recorded: str) -> None:
    """The parent session's record of the dispatch the subagent was started from."""
    parent = s.home / ".claude" / "projects" / ace._project_slug(s.project) / f"{s.harness}.jsonl"
    use = gate._tool_use("tooluse-test-1", "Agent", {"subagent_type": s.role, "prompt": prompt})
    use["timestamp"] = recorded
    parent.write_text(json.dumps(use) + "\n", encoding="utf-8")


def _copied_block_setup(tmp_path):
    """A dev dispatched now whose block was copied from a round three hours ago: its typed
    dispatched_at is that round's. The report on disk is that earlier round's, written two
    hours ago; this dispatch wrote nothing."""
    s = ace._l2_setup(tmp_path)
    now = datetime.now(timezone.utc)
    s.obligation["dispatched_at"] = _z(now - timedelta(hours=3))
    prompt = f'<obligation v="1">\n{json.dumps(s.obligation, indent=2)}\n</obligation>'
    edit = ("Edit", {"file_path": str(s.project / "src.txt"), "old_string": "alpha", "new_string": "beta"}, True)
    ace._write_obligation_transcript(s.home, s.project, s.harness, s.agent_id, prompt, [edit])
    _parent(s, prompt, _z(now))
    ace._l2_write(s, ace._l2_dev_report(s.task))
    when = (now - timedelta(hours=2)).timestamp()
    os.utime(s.project / s.art_path, (when, when))
    return s, _z(now)


def test_the_resolver_takes_the_parent_record_time(tmp_path):
    s, recorded = _copied_block_setup(tmp_path)
    resolution = ace._resolution(s.home, s.project, s.harness, s.agent_id, "dev")
    assert isinstance(resolution, obligation.Resolved), resolution
    assert resolution.obligation["dispatched_at"] == recorded


def test_a_copied_block_does_not_make_an_earlier_round_s_report_this_dispatch_s(tmp_path):
    """What the five-minute bound protected: the copied block's old time would have passed the
    earlier round's report as written for this dispatch. The record's time refuses it."""
    s, recorded = _copied_block_setup(tmp_path)
    proc = ace._l2_stop(s)
    ace._assert_warns(proc, s.art_path, "artifact_stale")
    assert f"dispatched_at {recorded!r}" in proc.stderr
