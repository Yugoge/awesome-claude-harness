"""Score events from facts (hooks/lib/score_events.py): lane QA's first_pass, fail and catch rules, and the observer.

Every case builds a fake session in a temporary folder: the main transcript (an opener, then each dispatch as the CLI
records it: the Agent tool_use with its obligation, and its tool_result with the timestamp and the toolUseResult), the
subagent transcripts that sit beside it, the project with its QA reports, and the config directory that holds the log.
Nothing reads the real home. A fake clock stamps every record, dispatch and report, so freshness is exact."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from hooks.lib import obligation, score_events, score_log  # noqa: E402

TASK = "20261109-120000"
OPENER = "<command-message>dev is running</command-message>\n<command-name>/dev</command-name>\n<command-args>x</command-args>"


def _z(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Cycle:
    """A /dev span in a temporary session: dispatches, QA reports and dev writes on one fake clock."""

    def __init__(self, tmp_path: Path):
        self.project, self.store = tmp_path / "proj", tmp_path / "store"
        (self.project / "docs" / "dev").mkdir(parents=True)
        (self.project / "src").mkdir()
        self.transcript = self.store / "sess.jsonl"
        self.subagents = self.store / "sess" / "subagents"
        self.subagents.mkdir(parents=True)
        self.config = tmp_path / "cfg"
        self.clock, self.count, self.agent, self.last_qa = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc), 0, {}, None
        self.write({"type": "user", "message": {"role": "user", "content": OPENER}})

    def write(self, record: dict, stamp: bool = True) -> None:
        if stamp:
            record["timestamp"] = _z(self.clock)
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def tick(self, seconds: int = 60) -> datetime:
        self.clock += timedelta(seconds=seconds)
        return self.clock

    def dispatch(self, role: str, *, task: str = TASK, lane=None, pipeline: str = "dev", profile: str = "singular",
                 artifacts=None, wrote=(), launch: bool = False, ok: bool = True, stamp: bool = True, suffix: bool = True) -> str:
        """One Agent dispatch, its result 30 s later; `wrote` are files its subagent transcript shows it writing."""
        self.count += 1
        ident, agent = f"toolu_{self.count:03d}", f"agent{self.count:03d}"
        tid = f"{task}-{lane}" if lane and suffix else task
        if artifacts is None:
            artifacts = [{"kind": "json", "path": f"docs/dev/{role}-report-{tid}.json", "schema": "dev-report.v2",
                          "identity": {"task_id": tid}}]
        doc = {"task_id": tid, "role": role, "pipeline": pipeline, "profile": profile, "artifacts": artifacts,
               "dispatched_at": _z(self.tick()).replace(".000Z", "Z")}
        if lane:
            doc.update(lane=lane, lane_set=["l1", "l2", "l3"], profile="fanout-lane")
        prompt = f"You are the {role} subagent.\n{obligation.serialize_obligation(doc)}"
        self.write({"type": "assistant", "cwd": str(self.project), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": "Agent", "input": {"subagent_type": role, "prompt": prompt}}]}})
        self.tick(30)
        shown = {"isAsync": True, "status": "async_launched", "agentId": agent} if launch else {
            "status": "completed", "agentId": agent, "content": [{"type": "text", "text": "done"}]}
        block = {"type": "tool_result", "tool_use_id": ident, "content": "done"}
        self.write({"type": "user", "message": {"role": "user", "content": [dict(block, **({} if ok else {"is_error": True}))]},
                    "toolUseResult": shown}, stamp)
        self.agent[ident] = agent
        records = [{"type": "user", "isSidechain": True, "cwd": str(self.project), "message": {"role": "user", "content": prompt}},
                   {"type": "summary", "summary": "a record without a message"},
                   {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [{"type": "text", "text": "start"}]}}]
        for n, name in enumerate(wrote):
            target = str(self.project / name)
            records += [{"type": "assistant", "isSidechain": True, "cwd": str(self.project), "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"w{n}", "name": "Write", "input": {"file_path": target, "content": "x = 2\n"}}]}},
                {"type": "user", "isSidechain": True, "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"w{n}", "content": "ok"}]}}]
        (self.subagents / f"agent-{agent}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return ident

    def qa(self, *, task: str = TASK, lane=None, pipeline: str = "dev", suffix: bool = True, **options) -> str:
        """A lane-QA dispatch declaring its qa-report.v2 file."""
        tid = f"{task}-{lane}" if lane and suffix else task
        artifacts = [{"kind": "json", "path": f"docs/dev/qa-report-{tid}.json", "schema": "qa-report.v2",
                      "identity": {"task_id": tid, "request_id": tid}}]
        self.last_qa = self.dispatch("qa", task=task, lane=lane, pipeline=pipeline, profile="final_verification",
                                     artifacts=artifacts, suffix=suffix, **options)
        return self.last_qa

    def report(self, status: str, failures=(), *, task: str = TASK, lane=None, mtime=None, text=None, kept: bool = True,
               suffix: bool = True) -> Path:
        """The QA report file, stamped now on the fake clock unless `mtime` says otherwise; the last QA dispatch's own
        transcript shows it writing the file (unless `kept` is False)."""
        tid = f"{task}-{lane}" if lane and suffix else task
        path = self.project / "docs" / "dev" / f"qa-report-{tid}.json"
        body = {"report_version": 2, "request_id": tid, "task_id": tid, "timestamp": _z(self.clock),
                "qa": {"status": status, "e2e_enforcement": {"status": "ran"}, "failures": list(failures)}}
        path.write_text(text if text is not None else json.dumps(body), encoding="utf-8")
        when = (mtime or self.clock).timestamp()
        os.utime(path, (when, when))
        if kept and self.last_qa:
            with (self.subagents / f"agent-{self.agent[self.last_qa]}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "assistant", "isSidechain": True, "cwd": str(self.project), "message": {
                    "role": "assistant", "content": [{"type": "tool_use", "id": "wr", "name": "Write",
                                                      "input": {"file_path": str(path), "content": path.read_text(encoding="utf-8")}}]}}) + "\n")
        return path

    def payload(self, **extra) -> dict:
        return dict({"tool_name": "Agent", "transcript_path": str(self.transcript), "cwd": str(self.project),
                     "session_id": "sess", "tool_use_id": "toolu_x"}, **extra)

    def observe(self, monkeypatch, **extra) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config))
        score_events.observe(self.payload(**extra))

    def sweep(self, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config))
        score_events.sweep(str(self.transcript), str(self.project))

    def rows(self) -> list[dict]:
        log = self.config / "logs" / "lifecycle.jsonl"
        return [row for _, row in score_log.read_lines(str(log))] if log.exists() else []

    def facts(self) -> list[tuple]:
        return sorted((r["event"], r["role"], r["points"]) for r in self.rows())


def failure(cause: str, location: str = "src/app.py:12", issue: str = "it breaks") -> dict:
    return {"severity": "major", "location": location, "issue": issue, "recommendation": "fix", "primary_cause": cause}


@pytest.fixture()
def cycle(tmp_path: Path) -> Cycle:
    return Cycle(tmp_path)


def fail_fix_pass(c: Cycle, monkeypatch, *, wrote, lane=None, task: str = TASK, cause: str = "dev_implementation",
                  location: str = "src/app.py:12"):
    """QA fails (named file at `location`), dev re-dispatched writes `wrote`, QA passes. Returns the pass dispatch id."""
    c.qa(task=task, lane=lane)
    c.report("fail", [failure(cause, location)], task=task, lane=lane)
    c.dispatch("dev", task=task, lane=lane, wrote=wrote)
    passing = c.qa(task=task, lane=lane)
    c.report("pass", task=task, lane=lane)
    return passing


# ---- the three rules -------------------------------------------------------------------------------------------

def test_a_first_pass_gives_dev_two_and_ba_one(cycle, monkeypatch):
    ident = cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]
    for row in cycle.rows():
        assert row["kind"] == "event" and row["task_id"] == TASK and row["ref"] == f"docs/dev/qa-report-{TASK}.json"
        assert row["key"] == f"qa_first_pass:{ident}:{row['role']}" and row["project"] == score_log.project_key(cycle.project)
        assert row["ts"] == "2026-11-09T12:01:30Z" and "\n" not in row["why"] and TASK not in row["why"]


@pytest.mark.parametrize("cause,expected", [
    ("dev_implementation", [("qa_fail", "dev", -6)]), ("ba_spec", [("qa_fail", "ba", -6)]),
    ("qa_oversight", []), ("environment", [])])
def test_a_failed_report_scores_only_the_two_scored_causes(cycle, monkeypatch, cause, expected):
    cycle.qa()
    cycle.report("fail", [failure(cause)])
    cycle.observe(monkeypatch)
    assert cycle.facts() == expected


def test_one_row_per_role_with_the_first_citing_failures_issue(cycle, monkeypatch):
    ident = cycle.qa()
    cycle.report("fail", [failure("environment", issue="no venv"), failure("dev_implementation", issue="first dev issue"),
                          failure("ba_spec", issue="spec gap"), failure("dev_implementation", issue="second dev issue")])
    cycle.observe(monkeypatch)
    by_role = {r["role"]: r for r in cycle.rows()}
    assert sorted(by_role) == ["ba", "dev"] and len(cycle.rows()) == 2
    assert by_role["dev"]["why"] == "first dev issue" and by_role["ba"]["why"] == "spec gap"
    assert by_role["dev"]["key"] == f"qa_fail:{ident}:dev" and by_role["ba"]["key"] == f"qa_fail:{ident}:ba"


def test_fail_then_a_fix_in_a_named_file_then_pass_is_a_catch(cycle, monkeypatch):
    passing = fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]
    catch = next(r for r in cycle.rows() if r["event"] == "qa_catch")
    assert catch["key"] == f"qa_catch:{passing}" and catch["ref"] == f"docs/dev/qa-report-{TASK}.json" and catch["task_id"] == TASK


@pytest.mark.parametrize("location", ["src/app.py:12", "src/app.py", "./src/app.py:3-9", "src/app.py:12:4"])
def test_the_file_part_of_the_location_is_compared(cycle, monkeypatch, location):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"], location=location)
    cycle.observe(monkeypatch)
    assert ("qa_catch", "qa", 1) in cycle.facts()


def test_an_absolute_location_inside_the_project_is_compared_project_relative(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"], location=f"{cycle.project}/src/app.py:7")
    cycle.observe(monkeypatch)
    assert ("qa_catch", "qa", 1) in cycle.facts()


def test_a_fix_that_touches_no_named_file_is_no_catch(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/other.py"])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_a_dev_dispatch_that_wrote_nothing_is_no_catch(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=[])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_only_the_next_dev_dispatch_counts(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.dispatch("dev", wrote=["src/other.py"])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_a_dev_dispatch_before_the_failure_is_not_the_fix(cycle, monkeypatch):
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.dispatch("dev", wrote=[])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_a_bash_command_naming_the_file_is_not_a_write(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.dispatch("dev")
    agent = cycle.agent[f"toolu_{cycle.count:03d}"]
    (cycle.subagents / f"agent-{agent}.jsonl").write_text(json.dumps({"type": "assistant", "isSidechain": True, "cwd": str(cycle.project),
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "cat src/app.py"}}]}}) + "\n")
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


@pytest.mark.parametrize("sweep_between_rounds", [False, True])
def test_at_most_two_catches_a_task_the_first_two_in_span_order(cycle, monkeypatch, sweep_between_rounds):
    passes = []
    for _ in range(3):
        passes.append(fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"]))
        if sweep_between_rounds:
            cycle.observe(monkeypatch)
    cycle.observe(monkeypatch)
    catches = sorted(r["key"] for r in cycle.rows() if r["event"] == "qa_catch")
    assert catches == sorted(f"qa_catch:{p}" for p in passes[:2])
    assert sum(1 for r in cycle.rows() if r["event"] == "qa_fail") == 3


def test_the_cap_counts_a_task_apart_from_another(cycle, monkeypatch):
    for task in (TASK, "20261109-130000"):
        for _ in range(2):
            fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"], task=task)
            cycle.observe(monkeypatch)
    assert sum(1 for r in cycle.rows() if r["event"] == "qa_catch") == 4


def test_a_pass_after_a_failure_is_not_a_first_pass(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "qa_first_pass" for r in cycle.rows())


def test_a_second_pass_of_a_lane_that_passed_is_not_a_first_pass(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


def test_a_pass_after_a_report_that_cannot_be_read_is_not_a_first_pass(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass", text="{not json")
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


@pytest.mark.parametrize("status", ["warning", "unknown"])
def test_a_report_without_a_pass_or_fail_gives_nothing(cycle, monkeypatch, status):
    cycle.qa()
    cycle.report(status)
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_lanes_are_judged_apart_and_task_ids_compare_canonically(cycle, monkeypatch):
    cycle.qa(lane="l1")
    cycle.report("pass", lane="l1")
    cycle.qa(lane="l2")
    cycle.report("fail", [failure("dev_implementation")], lane="l2")
    cycle.dispatch("dev", task=f"dev-{TASK}", lane="l2", wrote=["src/app.py"])  # the minted form of the same task id
    cycle.qa(lane="l2")
    cycle.report("pass", lane="l2")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6), ("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]
    assert {r["task_id"] for r in cycle.rows()} == {f"{TASK}-l1", f"{TASK}-l2"}


def test_lanes_that_share_a_task_id_are_judged_apart_by_the_lane_field(cycle, monkeypatch):
    cycle.qa(lane="l1", suffix=False)
    cycle.report("pass", lane="l1", suffix=False)
    cycle.qa(lane="l2", suffix=False)
    cycle.report("pass", lane="l2", suffix=False)
    cycle.observe(monkeypatch)
    assert len(cycle.rows()) == 4  # the second lane's pass is its own first pass


def test_another_lanes_dev_dispatch_is_not_the_fix(cycle, monkeypatch):
    cycle.qa(lane="l1", suffix=False)
    cycle.report("fail", [failure("dev_implementation")], lane="l1", suffix=False)
    cycle.dispatch("dev", lane="l2", suffix=False, wrote=["src/app.py"])
    cycle.qa(lane="l1", suffix=False)
    cycle.report("pass", lane="l1", suffix=False)
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_a_fix_in_a_file_under_docs_dev_still_counts(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["docs/dev/notes.md"], location="docs/dev/notes.md:3")
    cycle.observe(monkeypatch)
    assert ("qa_catch", "qa", 1) in cycle.facts()


def test_a_report_overwritten_by_the_next_dispatch_is_read_from_the_dispatchs_own_transcript(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")  # the same file: the failing report is gone from disk, and no sweep ran before
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]


def test_an_overwritten_report_its_dispatch_never_wrote_gives_nothing_and_the_next_pass_is_not_first(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")], kept=False)
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_a_report_read_before_it_was_overwritten_stays_scored(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.observe(monkeypatch)
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]


# ---- facts and when they exist ------------------------------------------------------------------------------------

def test_running_again_writes_no_new_row(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    before = (cycle.config / "logs" / "lifecycle.jsonl").read_bytes()
    cycle.observe(monkeypatch)
    cycle.observe(monkeypatch)
    assert (cycle.config / "logs" / "lifecycle.jsonl").read_bytes() == before and len(before.splitlines()) == 2


def test_a_launch_notice_is_scored_by_a_later_run_once_its_report_exists(cycle, monkeypatch):
    ident = cycle.qa(launch=True)
    cycle.observe(monkeypatch)  # the hook ran at launch: no report yet
    assert cycle.rows() == []
    cycle.tick(300)
    cycle.report("pass")
    cycle.dispatch("dev", wrote=[])  # a later dispatch of the span comes back
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]
    assert {r["key"] for r in cycle.rows()} == {f"qa_first_pass:{ident}:dev", f"qa_first_pass:{ident}:ba"}


def test_a_dispatch_without_a_result_yet_is_not_scored(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    lines = cycle.transcript.read_text().splitlines()
    cycle.transcript.write_text("\n".join(lines[:-1]) + "\n")  # the result record is not written yet
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_sweep_alone_writes_the_rows_observe_writes(tmp_path, monkeypatch):
    cycles = []
    for name in ("by-observe", "by-sweep"):
        c = Cycle(tmp_path / name)
        fail_fix_pass(c, monkeypatch, wrote=["src/app.py"])
        c.qa(lane="l2")
        c.report("pass", lane="l2")
        cycles.append(c)
    cycles[0].observe(monkeypatch)
    cycles[1].sweep(monkeypatch)
    rows = [[{k: v for k, v in r.items() if k not in ("project", "ref")} for r in c.rows()] for c in cycles]
    assert rows[0] == rows[1] and len(rows[0]) == 4
    cycles[1].sweep(monkeypatch)
    assert len(cycles[1].rows()) == 4


def test_a_sweep_later_scores_the_dispatch_whose_result_was_not_yet_in_the_transcript(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    lines = cycle.transcript.read_text().splitlines()
    cycle.transcript.write_text("\n".join(lines[:-1]) + "\n")  # the hook of the dispatch ran before its result was written
    cycle.observe(monkeypatch)
    assert cycle.rows() == []
    cycle.transcript.write_text("\n".join(lines) + "\n")
    cycle.sweep(monkeypatch)  # the rating moment: the close-time sweep
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


@pytest.mark.parametrize("args", [(None, None), (5, "/x"), ("/nonexistent/t.jsonl", "/x"), ("t.jsonl", 7), ("", ""), (b"x", b"y")])
def test_sweep_with_unusable_arguments_neither_raises_nor_prints(cycle, monkeypatch, capfd, args):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cycle.config))
    assert score_events.sweep(*args) is None
    assert capfd.readouterr() == ("", "") and cycle.rows() == []


def test_a_dispatch_that_came_back_as_an_error_is_not_scored(cycle, monkeypatch):
    cycle.qa(ok=False)
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


@pytest.mark.parametrize("case", ["missing", "not-json", "empty", "list", "no-qa-key", "bad-status", "stale", "directory"])
def test_a_missing_malformed_or_stale_report_gives_nothing(cycle, monkeypatch, case):
    cycle.qa()
    path = cycle.project / "docs" / "dev" / f"qa-report-{TASK}.json"
    if case == "not-json":
        cycle.report("pass", text="{broken")
    elif case == "empty":
        cycle.report("pass", text="")
    elif case == "list":
        cycle.report("pass", text="[1, 2]")
    elif case == "no-qa-key":
        cycle.report("pass", text='{"report_version": 2}')
    elif case == "bad-status":
        cycle.report("pass", text='{"qa": {"status": ["pass"]}}')
    elif case == "stale":
        cycle.report("pass", mtime=cycle.clock - timedelta(hours=1))
    elif case == "directory":
        path.mkdir()
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_a_malformed_failure_entry_does_not_stop_the_good_ones(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", ["oops", {"primary_cause": ["x"]}, {"primary_cause": None}, failure("ba_spec"), 7])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "ba", -6)]


def test_failures_that_are_not_a_list_give_no_row_and_no_error(cycle, monkeypatch):
    cycle.qa()
    path = cycle.report("fail")
    path.write_text(json.dumps({"qa": {"status": "fail", "failures": {"primary_cause": "dev_implementation"}}}))
    os.utime(path, (cycle.clock.timestamp(),) * 2)
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_the_row_time_is_the_clis_result_time_else_now(cycle, monkeypatch):
    cycle.qa(stamp=False)
    cycle.report("pass")
    before = datetime.now(timezone.utc).replace(microsecond=0)
    cycle.observe(monkeypatch)
    stamps = {r["ts"] for r in cycle.rows()}
    assert len(cycle.rows()) == 2 and all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s) for s in stamps)
    assert all(before <= datetime.fromisoformat(s.replace("Z", "+00:00")) <= datetime.now(timezone.utc) + timedelta(seconds=1) for s in stamps)


# ---- what it ignores --------------------------------------------------------------------------------------------

def test_a_payload_from_a_subagent_is_ignored(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch, agent_id="a123")
    assert cycle.rows() == [] and not cycle.config.exists()


@pytest.mark.parametrize("name", ["Bash", "Edit", "AskUserQuestion", None])
def test_only_the_dispatch_tool_is_observed(cycle, monkeypatch, name):
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch, tool_name=name)
    assert cycle.rows() == []


def test_the_legacy_task_name_is_observed(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch, tool_name="Task")
    assert len(cycle.rows()) == 2


def test_close_time_qa_is_ignored_by_these_rules(cycle, monkeypatch):
    cycle.qa(pipeline="close")
    cycle.report("pass")
    cycle.qa(pipeline="close", task="20261109-130000")
    cycle.report("fail", [failure("dev_implementation")], task="20261109-130000")
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_a_ba_validation_qa_is_not_lane_qa(cycle, monkeypatch):
    artifacts = [{"kind": "json", "path": f"docs/dev/ba-qa-report-{TASK}.json", "schema": "ba-qa-report.v1", "identity": {"task_id": TASK}}]
    cycle.qa()
    cycle.dispatch("qa", profile="ba_validation", artifacts=artifacts)
    (cycle.project / "docs" / "dev" / f"ba-qa-report-{TASK}.json").write_text('{"verdict": "pass"}')
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_no_command_span_gives_nothing(tmp_path, monkeypatch):
    cycle = Cycle(tmp_path)
    cycle.transcript.write_text("")
    cycle.write({"type": "user", "message": {"role": "user", "content": "just a plain prompt"}})
    cycle.observe(monkeypatch)
    assert cycle.rows() == [] and not cycle.config.exists()


def test_dispatches_before_the_span_opened_are_not_swept(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    cycle.write({"type": "user", "message": {"role": "user", "content": OPENER.replace("/dev", "/redev")}})
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


# ---- failure and concurrency ------------------------------------------------------------------------------------

def test_one_rule_raising_does_not_stop_the_others(cycle, monkeypatch):
    def boom(ctx):
        yield {"event": "qa_fail", "role": "dev", "task_id": TASK, "key": "boom:1", "why": "first"}
        raise RuntimeError("rule failed")

    def odd(ctx):
        yield {"event": "no_such_event", "role": "dev", "task_id": TASK, "key": "odd:1", "why": "x"}

    cycle.qa()
    cycle.report("pass")
    monkeypatch.setattr(score_events, "RULES", [boom, odd, *score_events.RULES, boom])
    cycle.observe(monkeypatch)
    assert ("qa_first_pass", "dev", 2) in cycle.facts() and ("qa_first_pass", "ba", 1) in cycle.facts()
    assert {r["key"] for r in cycle.rows() if r["event"] == "qa_fail"} <= {"boom:1"}


def test_an_event_whose_role_the_points_table_does_not_know_is_no_row(cycle, monkeypatch):
    def unscored(ctx):
        yield {"event": "qa_fail", "role": "qa", "task_id": TASK, "key": "unscored:1", "why": "x"}  # the table scores qa_fail for dev and ba

    cycle.qa()
    cycle.report("pass")
    monkeypatch.setattr(score_events, "RULES", [unscored, *score_events.RULES])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


def test_a_dispatch_result_that_is_not_an_object_does_not_stop_the_sweep(cycle, monkeypatch):
    cycle.dispatch("dev")
    cycle.qa()
    cycle.report("pass")
    lines = [json.loads(line) for line in cycle.transcript.read_text().splitlines()]
    next(r for r in lines if r.get("toolUseResult", {}).get("agentId") == "agent001")["toolUseResult"] = "plain text"
    cycle.transcript.write_text("".join(json.dumps(r) + "\n" for r in lines))
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


def test_a_rule_is_added_by_listing_one_function(cycle, monkeypatch):
    def lane_seen(ctx):
        for d in ctx["ds"]:
            if d["who"] == "dev":
                yield score_events._event(ctx, d, "rerun_gap", "dev", "dev dispatched", f"rerun_gap:{d['id']}")

    cycle.dispatch("dev")
    monkeypatch.setattr(score_events, "RULES", [*score_events.RULES, lane_seen])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("rerun_gap", "dev", -2)]


GARBAGE = [None, [], "x", 7, {}, {"tool_name": "Agent"}, {"tool_name": "Agent", "transcript_path": 5},
           {"tool_name": "Agent", "transcript_path": "/nonexistent/t.jsonl", "cwd": "/nonexistent"},
           {"tool_name": "Agent", "transcript_path": "", "cwd": ""}, {"tool_name": ["Agent"]}, {"agent_id": "a", "tool_name": "Agent"}]


@pytest.mark.parametrize("payload", GARBAGE, ids=range(len(GARBAGE)))
def test_garbage_payloads_neither_raise_nor_print(cycle, monkeypatch, payload):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cycle.config))
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        assert score_events.observe(payload) is None
    assert out.getvalue() == err.getvalue() == "" and cycle.rows() == []


def test_a_payload_without_a_working_directory_neither_raises_nor_prints(cycle, monkeypatch, capfd):
    cycle.qa()
    cycle.report("pass")
    payload = cycle.payload()
    del payload["cwd"]
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cycle.config))
    assert score_events.observe(payload) is None
    assert capfd.readouterr() == ("", "") and cycle.rows() == []


def test_a_good_run_prints_nothing(cycle, monkeypatch, capfd):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    assert capfd.readouterr() == ("", "") and len(cycle.rows()) == 2


def test_an_unreadable_log_never_raises(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    log = cycle.config / "logs" / "lifecycle.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"kind": "event", "key": "a"}\nnot json\n{"kind": "event", "key": "b"}\n')
    cycle.observe(monkeypatch)
    assert log.read_text().count("\n") == 3


def test_observers_racing_give_each_row_once(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import score_events; score_events.observe(json.loads(sys.argv[2]))")
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cycle.config), PYTHONDONTWRITEBYTECODE="1")
    procs = [subprocess.Popen([sys.executable, "-B", "-c", code, str(REPO_ROOT / "hooks" / "lib"), json.dumps(cycle.payload())],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)]
    outputs = [p.communicate() for p in procs]
    assert all(p.returncode == 0 for p in procs) and all(out == (b"", b"") for out in outputs)
    keys = [r["key"] for r in cycle.rows()]
    assert len(keys) == len(set(keys)) == 2 and cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]


def test_a_big_transcript_is_read_from_the_span_on(cycle, monkeypatch):
    """~5 MB of earlier session before the opener, ten dispatches in the span: one run stays well under a second."""
    old = cycle.transcript.read_text()
    filler = json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 4000}]}}) + "\n"
    cycle.transcript.write_text(filler * 1300 + old)
    for n in range(4):
        cycle.dispatch("dev", lane="l1" if n % 2 else None, wrote=[])
    for n in range(3):
        cycle.qa(lane=f"l{n + 1}" if n else None)
        cycle.report("pass", lane=f"l{n + 1}" if n else None)
    cycle.dispatch("ba")
    cycle.dispatch("dev")
    assert cycle.transcript.stat().st_size > 5_000_000
    started = time.perf_counter()
    cycle.observe(monkeypatch)
    assert time.perf_counter() - started < 2.0 and len(cycle.rows()) == 6
