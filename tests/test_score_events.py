"""Score events from facts (hooks/lib/score_events.py): lane QA's first_pass, fail and catch rules, the close-time rules
escaped and close_catch, and the observer.

Every case builds a fake session in a temporary folder: the main transcript (an opener, then each dispatch as the CLI
records it: the Agent tool_use with its obligation, and its tool_result with the timestamp and the toolUseResult), the
subagent transcripts and their meta.json that sit beside it (the CLI's store layout: <root>/<project slug>/<session>.jsonl),
the project with its QA reports and close report, and the config directory that holds the log. Nothing reads the real
home. A fake clock stamps every record, dispatch and report, so freshness is exact.

The close-time shapes follow what the pipeline really produces: the close-QA obligation is the one commands/close.md
Step 2 prints (read from that file); a round's section is the one tests/replay/drivers/close.py appends to
docs/dev/close-report-<task>.md (a "## Findings" list of "- <path>: <detail>" lines, then the verdict line last), written
with the Write tool and handed to scripts/close-report-append.py, or put in a Bash heredoc; its reply ends in the
verdict line (CLOSE_FINDINGS: <n> items, or CLOSE: YES)."""

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
from hooks.lib import obligation, requirement_round, score_events, score_log  # noqa: E402

TASK = "20261109-120000"
REPORT = f"docs/dev/dev-report-{TASK}.json"  # dev's own report, and ba's ticket: the files a close finding cites
TICKET = f"docs/dev/ticket-{TASK}.md"
OPENER = "<command-message>dev is running</command-message>\n<command-name>/dev</command-name>\n<command-args>x</command-args>"
# the close-QA obligation commands/close.md Step 2 prints, with <TASK_ID> to bind
CLOSE_OBLIGATION = next(line for line in (REPO_ROOT / "commands" / "close.md").read_text(encoding="utf-8").splitlines()
                        if line.startswith('{"task_id":"<TASK_ID>","role":"qa","pipeline":"close"'))


def _z(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Cycle:
    """A /dev span in a temporary session: dispatches, QA reports and dev writes on one fake clock."""

    def __init__(self, tmp_path: Path, session: str = "sess", command: str = "dev"):
        self.project = tmp_path / "proj"
        (self.project / "docs" / "dev").mkdir(parents=True, exist_ok=True)
        (self.project / "src").mkdir(exist_ok=True)
        self.store = tmp_path / "projects" / obligation.project_slug(self.project)
        self.session = session
        self.transcript = self.store / f"{session}.jsonl"
        self.subagents = self.store / session / "subagents"
        self.subagents.mkdir(parents=True, exist_ok=True)
        self.config = tmp_path / "cfg"
        self.clock, self.count, self.agent, self.last_qa = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc), 0, {}, None
        self.opener(command)

    def write(self, record: dict, stamp: bool = True) -> None:
        if stamp:
            record["timestamp"] = _z(self.clock)
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def tick(self, seconds: int = 60) -> datetime:
        self.clock += timedelta(seconds=seconds)
        return self.clock

    def dispatch(self, role: str, *, task: str = TASK, lane=None, pipeline: str = "dev", profile: str = "singular",
                 artifacts=None, wrote=(), launch: bool = False, ok: bool = True, stamp: bool = True, suffix: bool = True,
                 reply: str = "done", extra=None, declared: bool = True) -> str:
        """One Agent dispatch, its result 30 s later; `wrote` are files its subagent transcript shows it writing, and
        (with `declared`) so are the artifacts it declares: a producer that finishes writes them. QA's reports are
        written by report() and a close round's by complete_close_qa()."""
        self.count += 1
        ident, agent = f"toolu_{self.count:03d}", f"agent{self.count:03d}"
        tid = f"{task}-{lane}" if lane and suffix else task
        if artifacts is None:
            artifacts = [{"kind": "json", "path": f"docs/dev/{role}-report-{tid}.json", "schema": "dev-report.v2",
                          "identity": {"task_id": tid}}]
        doc = {"task_id": tid, "role": role, "pipeline": pipeline, "profile": profile, "artifacts": artifacts,
               "dispatched_at": _z(self.tick()).replace(".000Z", "Z")}
        doc.update(extra or {})
        if lane:
            doc.update(lane=lane, lane_set=["l1", "l2", "l3"], profile="fanout-lane")
        prompt = f"You are the {role} subagent.\n{obligation.serialize_obligation(doc)}"
        self.write({"type": "assistant", "cwd": str(self.project), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": "Agent", "input": {"subagent_type": role, "prompt": prompt}}]}})
        self.tick(30)
        shown = {"isAsync": True, "status": "async_launched", "agentId": agent} if launch else {
            "status": "completed", "agentId": agent, "content": [{"type": "text", "text": reply}]}
        block = {"type": "tool_result", "tool_use_id": ident, "content": "Async agent launched successfully." if launch else reply}
        self.write({"type": "user", "message": {"role": "user", "content": [dict(block, **({} if ok else {"is_error": True}))]},
                    "toolUseResult": shown}, stamp)
        self.agent[ident] = agent
        records = [{"type": "user", "isSidechain": True, "cwd": str(self.project), "message": {"role": "user", "content": prompt}},
                   {"type": "summary", "summary": "a record without a message"},
                   {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [{"type": "text", "text": "start"}]}}]
        for n, name in enumerate([*wrote, *([a["path"] for a in artifacts if a.get("path")] if declared and role != "qa" else [])]):
            target = str(self.project / name)
            records += [{"type": "assistant", "isSidechain": True, "cwd": str(self.project), "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"w{n}", "name": "Write", "input": {"file_path": target, "content": "x = 2\n"}}]}},
                {"type": "user", "isSidechain": True, "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"w{n}", "content": "ok"}]}}]
        (self.subagents / f"agent-{agent}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        (self.subagents / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": role, "toolUseId": ident}), encoding="utf-8")
        return ident

    def opener(self, command: str) -> None:
        """The owner types a harness command: a new span."""
        self.write({"type": "user", "message": {"role": "user", "content": OPENER.replace("dev", command)}})

    def finish(self, ident: str, calls=(), reply: str = "") -> None:
        """What a dispatch's subagent does last, in its own transcript: the tool calls, then its reply."""
        records = [{"type": "assistant", "isSidechain": True, "cwd": str(self.project), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"c{n}", "name": name, "input": args}]}} for n, (name, args) in enumerate(calls)]
        records.append({"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "stop_reason": "end_turn",
                                                                                "content": [{"type": "text", "text": reply}]}})
        with (self.subagents / f"agent-{self.agent[ident]}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(r) + "\n" for r in records))

    def close_qa(self, findings=(), *, verdict=None, task: str = TASK, launch: bool = False, via: str = "Write") -> str:
        """One close-QA round: the dispatch, and (unless it came back as a launch notice) the round's work."""
        verdict = verdict or (f"CLOSE_FINDINGS: {len(findings)} items" if findings else "CLOSE: YES")
        doc = json.loads(CLOSE_OBLIGATION.replace("<TASK_ID>", task))
        ident = self.dispatch("qa", task=task, pipeline="close", profile=doc["profile"], artifacts=doc["artifacts"],
                              extra={"consistency": doc["consistency"]}, launch=launch,
                              reply=f'{{\n  "status": "completed"\n}}\n\n{verdict}')
        if not launch:
            self.complete_close_qa(ident, findings, verdict, task=task, via=via)
        return ident

    def complete_close_qa(self, ident: str, findings, verdict: str, *, task: str = TASK, via: str = "Write") -> None:
        """The round's section appended to the close report, and the subagent's calls and last words."""
        report = self.project / "docs" / "dev" / f"close-report-{task}.md"
        number = (report.read_text(encoding="utf-8").count("## Close attempt") if report.exists() else 0) + 1
        lines = [f"## Close attempt (round {number}) {_z(self.clock)}", "", f"Task-id: {task}", "Workflow Integrity Dimension:",
                 "1. Downstream consumability: PASS - Step 0's chain_pass covers the chain /commit consumes",
                 "Codex consultation: codex_status: disabled_by_user"]
        if findings:  # a (path, detail) pair is a finding line; a string is written as it is
            lines += ["", "## Findings"] + [f"- {item[0]}: {item[1]}" if isinstance(item, tuple) else item for item in findings]
        text = "\n".join(lines) + f"\n\n{verdict}\n"
        with report.open("a", encoding="utf-8") as handle:
            handle.write(text)
        helper = f'python3 ~/.claude/scripts/close-report-append.py --report-path "{report}" --section-file /tmp/claude-scratch/s.md --task-id "{task}"'
        calls = ([("Write", {"file_path": "/tmp/claude-scratch/s.md", "content": text}), ("Bash", {"command": helper})] if via == "Write"
                 else [("Bash", {"command": f"cat > /tmp/claude-scratch/s.md <<'EOF'\n{text}EOF\n{helper}"})])
        self.finish(ident, calls, f'{{\n  "status": "completed"\n}}\n\n{verdict}')

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
        if self.last_qa:  # kept=False: written by a shell command that names it, so no Write of it is on record
            tool = ("Write", {"file_path": str(path), "content": path.read_text(encoding="utf-8")}) if kept else ("Bash", {"command": f"python3 mk.py > {path}"})
            ident = f"wr{path.stat().st_mtime_ns}"
            records = [{"type": "assistant", "isSidechain": True, "cwd": str(self.project), "message": {
                "role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": tool[0], "input": tool[1]}]}},
                {"type": "user", "isSidechain": True, "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": ident, "content": "ok"}]}}]
            with (self.subagents / f"agent-{self.agent[self.last_qa]}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("".join(json.dumps(r) + "\n" for r in records))
        return path

    def payload(self, **extra) -> dict:
        return dict({"tool_name": "Agent", "transcript_path": str(self.transcript), "cwd": str(self.project),
                     "session_id": self.session, "tool_use_id": "toolu_x"}, **extra)

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


@pytest.mark.parametrize("bookkeeping", [REPORT, "docs/dev/notes.md:3", ".claude/dev-registry/dev-x/dev.json", ".claude/scratch/s1/a.txt"])
def test_a_failure_located_in_a_bookkeeping_file_gives_no_catch(cycle, monkeypatch, bookkeeping):
    # a QA that names the dev's own report (which the re-dispatch rewrites anyway) is not credited with a catch
    fail_fix_pass(cycle, monkeypatch, wrote=[bookkeeping.split(":")[0]], location=bookkeeping)
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


def test_a_bookkeeping_location_does_not_hide_a_product_file_failure_that_was_fixed(cycle, monkeypatch):
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation", REPORT + ":1"), failure("dev_implementation", "src/app.py:12")])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert ("qa_catch", "qa", 1) in cycle.facts()


def test_a_product_file_failure_still_needs_the_product_file_written(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=[REPORT, "docs/dev/notes.md"])  # only bookkeeping written; the failure names src/app.py
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_fail", "dev", -6)]


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


# ---- the close-time rules: escaped and close_catch ---------------------------------------------------------------

def closed(c: Cycle, lane_qa: str = "pass", close: bool = True) -> None:
    """The /dev span: ba's ticket, dev's work (it wrote src/app.py), lane QA's verdict; then the owner types /close."""
    c.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    c.dispatch("dev", wrote=["src/app.py"])
    c.qa()
    c.report(lane_qa, [failure("dev_implementation")] if lane_qa == "fail" else [])
    if close:
        c.opener("close")


def test_a_close_finding_on_a_dev_artifact_after_lane_qa_passed_is_escaped_for_dev_and_lane_qa(cycle, monkeypatch):
    closed(cycle)
    ident = cycle.close_qa([(REPORT, "the report lists a file dev never wrote")])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]
    for row in cycle.rows():
        assert row["key"] == f"escaped:{TASK}:{REPORT}:{row['role']}" and row["task_id"] == TASK and row["ref"] == REPORT
        assert row["ts"] == "2026-11-09T12:06:00Z" and "\n" not in row["why"] and TASK not in row["why"]


@pytest.mark.parametrize("via", ["Write", "Bash"])
@pytest.mark.parametrize("cited", ["src/app.py", "src/app.py:12", "./src/app.py", "`src/app.py`"])
def test_a_finding_on_a_product_file_goes_to_the_dispatch_that_wrote_it(cycle, monkeypatch, cited, via):
    closed(cycle)
    cycle.close_qa([(cited, "add() has no contract")], via=via)
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]


def test_the_last_section_a_round_wrote_is_the_one_that_counts(cycle, monkeypatch):
    closed(cycle)
    ident = cycle.close_qa(launch=True)
    draft = "## Close attempt (round 1) x\n\n## Findings\n- " + TICKET + ": a draft\n\nCLOSE_FINDINGS: 1 items\n"
    final = "## Close attempt (round 1) x\n\n## Findings\n- " + REPORT + ": the final text\n\nCLOSE_FINDINGS: 1 items\n"
    cycle.finish(ident, [("Write", {"file_path": "/tmp/claude-scratch/s.md", "content": draft}),
                         ("Write", {"file_path": "/tmp/claude-scratch/s.md", "content": final})], "CLOSE_FINDINGS: 1 items")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]


def test_a_close_in_a_later_session_reads_the_producer_and_its_lane_qa_from_the_dev_session(tmp_path, monkeypatch):
    earlier = Cycle(tmp_path, session="earlier")
    closed(earlier, close=False)
    later = Cycle(tmp_path, session="later", command="close")
    later.clock = earlier.clock + timedelta(hours=1)
    later.close_qa([(REPORT, "a defect")])
    later.dispatch("dev", wrote=[REPORT])
    later.close_qa()
    later.observe(monkeypatch)
    assert later.facts() == [("close_catch", "close-qa", 1), ("escaped", "dev", -7), ("escaped", "qa", -3)]
    assert {r["key"] for r in later.rows()} == {f"escaped:{TASK}:{REPORT}:dev", f"escaped:{TASK}:{REPORT}:qa", f"close_catch:{TASK}:{REPORT}"}


def test_each_finding_goes_to_its_own_producer_and_lane_qa_is_charged_for_each(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "first"), (TICKET, "second")])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "ba", -7), ("escaped", "dev", -7), ("escaped", "qa", -3), ("escaped", "qa", -3)]
    assert {r["key"] for r in cycle.rows()} == {f"escaped:{TASK}:{REPORT}:dev", f"escaped:{TASK}:{REPORT}:qa",
                                                f"escaped:{TASK}:{TICKET}:ba", f"escaped:{TASK}:{TICKET}:qa"}


@pytest.mark.parametrize("lane_qa", ["fail", "warning", "none"])
def test_no_escape_when_lane_qa_had_not_passed(cycle, monkeypatch, lane_qa):
    if lane_qa == "none":
        cycle.dispatch("dev", wrote=["src/app.py"])
        cycle.opener("close")
    else:
        closed(cycle, lane_qa)
    cycle.close_qa([(REPORT, "a defect")])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows())


def test_lane_qa_is_judged_for_the_producers_own_lane(cycle, monkeypatch):
    for lane, status in (("l1", "pass"), ("l2", "fail")):
        cycle.dispatch("dev", lane=lane, wrote=[f"src/{lane}.py"])
        cycle.qa(lane=lane)
        cycle.report(status, [failure("dev_implementation")] if status == "fail" else [], lane=lane)
    cycle.opener("close")
    cycle.close_qa([(f"docs/dev/dev-report-{TASK}-l1.json", "x"), (f"docs/dev/dev-report-{TASK}-l2.json", "y")])
    cycle.observe(monkeypatch)
    one = f"docs/dev/dev-report-{TASK}-l1.json"
    assert sorted(r["key"] for r in cycle.rows() if r["event"] == "escaped") == [f"escaped:{TASK}:{one}:dev", f"escaped:{TASK}:{one}:qa"]


@pytest.mark.parametrize("cited", ["README.md", f"docs/dev/context-{TASK}.json", "../outside.txt", "toy/missing.py:3"])
def test_a_finding_with_no_declaring_dispatch_gives_no_row_and_no_error(cycle, monkeypatch, capfd, cited):
    closed(cycle)
    cycle.close_qa([(cited, "nobody owes this")])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows()) and capfd.readouterr() == ("", "")


def test_a_close_time_qa_report_is_not_the_producers_lane_qa(cycle, monkeypatch):
    closed(cycle, "fail")
    own = {"kind": "json", "path": "docs/dev/close-qa-report.json", "schema": "qa-report.v2", "identity": {"task_id": TASK}}
    cycle.dispatch("qa", pipeline="close", profile="final_verification", artifacts=[own], declared=False)
    (cycle.project / own["path"]).write_text(json.dumps({"qa": {"status": "pass"}}))
    os.utime(cycle.project / own["path"], (cycle.clock.timestamp(),) * 2)  # fresh on the fake clock
    cycle.close_qa([(REPORT, "a defect")])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows())


def test_a_finding_on_a_close_time_artifact_is_no_escape(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(f"docs/dev/close-report-{TASK}.md", "the report is defective")])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows())


def test_a_clean_close_gives_close_qa_nothing(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert not any(r["event"] in ("escaped", "close_catch") for r in cycle.rows())


def test_a_fix_by_the_producer_and_a_landing_round_is_close_qas_catch(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "the report lists a file dev never wrote")])
    cycle.dispatch("dev", wrote=[REPORT])
    landing = cycle.close_qa()
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("close_catch", "close-qa", 1), ("escaped", "dev", -7), ("escaped", "qa", -3)]
    catch = next(r for r in cycle.rows() if r["event"] == "close_catch")
    assert catch["key"] == f"close_catch:{TASK}:{REPORT}" and catch["ref"] == REPORT and catch["task_id"] == TASK and landing


@pytest.mark.parametrize("fixed,expected", [([REPORT], {0}), ([TICKET], {1}), ([REPORT, TICKET], {0, 1}), ([], set())])
def test_the_catch_is_one_row_for_each_finding_whose_file_was_fixed(cycle, monkeypatch, fixed, expected):
    closed(cycle)
    cycle.close_qa([(REPORT, "first"), (TICKET, "second")])
    if REPORT in fixed:
        cycle.dispatch("dev", wrote=[REPORT])
    if TICKET in fixed:
        cycle.dispatch("ba", wrote=[TICKET], artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert {r["key"] for r in cycle.rows() if r["event"] == "close_catch"} == {f"close_catch:{TASK}:{[REPORT, TICKET][i]}" for i in expected}


def test_a_finding_is_caught_once_by_the_first_round_that_lands(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa()
    second = cycle.close_qa()  # a second landing round, say a /close typed again
    cycle.observe(monkeypatch)
    catches = [r for r in cycle.rows() if r["event"] == "close_catch"]
    assert [r["key"] for r in catches] == [f"close_catch:{TASK}:{REPORT}"] and second not in catches[0]["key"]


def test_a_fix_after_the_landing_round_is_no_catch(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")])
    cycle.close_qa()
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())


@pytest.mark.parametrize("fix", ["wrote nothing", "wrote another file", "another role wrote it", "no dispatch"])
def test_no_catch_when_the_producers_fix_did_not_write_the_cited_file(cycle, monkeypatch, fix):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")])
    if fix == "wrote nothing":
        cycle.dispatch("dev", wrote=[], declared=False)
    elif fix == "wrote another file":
        cycle.dispatch("dev", wrote=["src/other.py"], declared=False)
    elif fix == "another role wrote it":
        cycle.dispatch("ba", wrote=[REPORT], artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())


def test_no_catch_while_no_later_round_has_landed(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())
    cycle.close_qa([(REPORT, "still a defect")])  # the next round opened a finding again
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa(verdict="CLOSE: YES - with disclosures: 1 items")  # any landed form lands
    cycle.observe(monkeypatch)
    assert sum(r["event"] == "close_catch" for r in cycle.rows()) == 1  # the same file's finding, raised in two rounds, is one catch


def test_a_fix_written_before_the_finding_is_no_catch(cycle, monkeypatch):
    closed(cycle)
    cycle.dispatch("dev", wrote=[REPORT])  # dev wrote the report before the round that opened a finding on it
    cycle.close_qa([(REPORT, "a defect")])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())


def test_running_the_close_rules_again_adds_no_row(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect"), (TICKET, "another")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    before = (cycle.config / "logs" / "lifecycle.jsonl").read_bytes()
    cycle.observe(monkeypatch)
    cycle.sweep(monkeypatch)
    assert (cycle.config / "logs" / "lifecycle.jsonl").read_bytes() == before and len(before.splitlines()) == 5


def test_a_close_round_that_came_back_as_a_launch_notice_is_scored_by_a_later_sweep(cycle, monkeypatch):
    closed(cycle)
    first = cycle.close_qa([(REPORT, "a defect")], launch=True)  # the hook ran at launch: the round's work is not done yet
    cycle.observe(monkeypatch)
    assert cycle.rows() == []
    cycle.complete_close_qa(first, [(REPORT, "a defect")], "CLOSE_FINDINGS: 1 items")
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]
    landing = cycle.close_qa(launch=True)
    cycle.sweep(monkeypatch)
    assert not any(r["event"] == "close_catch" for r in cycle.rows())
    cycle.complete_close_qa(landing, [], "CLOSE: YES")
    cycle.sweep(monkeypatch)
    assert [r["key"] for r in cycle.rows() if r["event"] == "close_catch"] == [f"close_catch:{TASK}:{REPORT}"] and landing


@pytest.mark.parametrize("findings", [
    [], ["- just words, no file", "-", "* a: b", "", "## Not findings", f"- {REPORT}: a bullet of another section"],
    ["- : no path"], ["no bullet at all"]])
def test_malformed_or_empty_findings_give_nothing(cycle, monkeypatch, capfd, findings):
    closed(cycle)
    cycle.close_qa(findings, verdict="CLOSE_FINDINGS: 2 items")
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows()) and capfd.readouterr() == ("", "")


def test_a_landed_round_opens_no_finding_whatever_its_text_holds(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a note on a line of the report")], verdict="CLOSE: YES")
    cycle.observe(monkeypatch)
    assert not any(r["event"] in ("escaped", "close_catch") for r in cycle.rows())


def test_a_round_without_a_verdict_line_opens_and_lands_nothing(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")], verdict="CLOSE_REPORT_APPEND_ERROR: append: no space left on device")
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert not any(r["event"] in ("escaped", "close_catch") for r in cycle.rows())


def test_a_close_report_nobody_wrote_a_section_for_gives_nothing(cycle, monkeypatch):
    closed(cycle)
    ident = cycle.close_qa(launch=True)
    cycle.finish(ident, [], "CLOSE_FINDINGS: 1 items")  # the reply says a finding opened; the QA's own calls show no section
    cycle.observe(monkeypatch)
    assert not any(r["event"] == "escaped" for r in cycle.rows())


def test_the_close_rules_and_the_qa_rules_share_one_transcript(cycle, monkeypatch):
    cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("fail", [failure("dev_implementation")])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.qa()
    cycle.report("pass")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]
    cycle.opener("close")
    cycle.close_qa([(REPORT, "a defect")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    cycle.sweep(monkeypatch)
    assert cycle.facts() == [("close_catch", "close-qa", 1), ("escaped", "dev", -7), ("escaped", "qa", -3),
                             ("qa_catch", "qa", 1), ("qa_fail", "dev", -6)]
    keys = [r["key"] for r in cycle.rows()]
    assert len(keys) == len(set(keys))


def test_a_failing_close_rule_does_not_stop_the_qa_rules(cycle, monkeypatch):
    def boom(ctx):
        raise RuntimeError("close rule failed")
        yield

    cycle.qa()
    cycle.report("pass")
    monkeypatch.setattr(score_events, "_close_qa", lambda ctx: 1 / 0)
    monkeypatch.setattr(score_events, "RULES", [*score_events.RULES, boom])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


# ---- rerun_gap: a dispatch after one that left its declared artifacts unwritten -----------------------------------

def gaps(c: Cycle) -> list[dict]:
    return [r for r in c.rows() if r["event"] == "rerun_gap"]


@pytest.mark.parametrize("wrote", [[], ["src/app.py"]])
def test_a_dispatch_after_one_that_wrote_no_declared_artifact_scores_a_gap(cycle, monkeypatch, wrote):
    cycle.dispatch("dev", wrote=wrote, declared=False)
    again = cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("rerun_gap", "dev", -2)]
    row = cycle.rows()[0]
    assert row["key"] == f"rerun_gap:{again}" and row["task_id"] == TASK and TASK not in row["why"] and "\n" not in row["why"]
    assert row["ts"] == "2026-11-09T12:03:00Z"  # when the dispatch that was a rerun came back, not its predecessor


def test_every_dispatch_after_a_dispatch_that_left_a_gap_scores_one(cycle, monkeypatch):
    cycle.dispatch("dev", declared=False)
    second = cycle.dispatch("dev", declared=False)
    third = cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    assert sorted(r["key"] for r in gaps(cycle)) == [f"rerun_gap:{second}", f"rerun_gap:{third}"]


@pytest.mark.parametrize("role", ["ba", "qa"])
def test_the_gap_is_the_groups_scored_identity(cycle, monkeypatch, role):
    if role == "qa":
        cycle.qa()  # no report written by the first QA dispatch
        cycle.qa()
    else:
        cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}], declared=False)
        cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.observe(monkeypatch)
    assert [r["role"] for r in gaps(cycle)] == [role]


def test_a_first_dispatch_is_no_gap(cycle, monkeypatch):
    cycle.dispatch("dev", declared=False)
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_a_re_dispatch_after_a_qa_failure_is_no_gap(cycle, monkeypatch):
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_catch", "qa", 1), ("qa_fail", "dev", -6)] and not gaps(cycle)


def test_a_re_dispatch_after_a_close_finding_is_no_gap(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a defect")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


def test_a_re_dispatch_after_a_clarification_is_no_gap(cycle, monkeypatch):
    cycle.dispatch("ba", wrote=[f"docs/dev/producer-question-{TASK}-ba.json"], declared=False,
                   artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


@pytest.mark.parametrize("round_file, gap", [
    (requirement_round.ROUND.format(task=TASK, n=2), False),  # the final BA asked for another round writes it instead of its artifacts (D29)
    (requirement_round.ROUND.format(task=TASK, n=4), False),  # no cap on the rounds
    (requirement_round.ROUND.format(task="20261109-130000", n=2), True),  # another task's round is not this task's write
    (None, True)])  # it wrote nothing at all
def test_a_requirement_round_of_the_task_is_a_write_of_the_dispatch_that_asked_it(cycle, monkeypatch, round_file, gap):
    ticket = [{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}]
    cycle.dispatch("ba", wrote=[round_file] if round_file else [], declared=False, artifacts=ticket)
    again = cycle.dispatch("ba", artifacts=ticket)
    cycle.observe(monkeypatch)
    assert [(r["role"], r["key"]) for r in gaps(cycle)] == ([("ba", f"rerun_gap:{again}")] if gap else [])


def test_a_dispatch_that_declares_no_file_is_no_gap(cycle, monkeypatch):
    answer = [{"kind": "response_line", "terminal_line_regex": "^done$"}]
    cycle.dispatch("dev", artifacts=answer, declared=False)
    cycle.dispatch("dev", artifacts=answer)
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


def test_a_dispatch_that_ended_in_an_api_error_is_not_a_dispatch_to_compare(cycle, monkeypatch):
    cycle.dispatch("dev", declared=False, ok=False)
    cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


@pytest.mark.parametrize("how", ["a shell command naming the artifact", "a Write of it"])
def test_any_tool_call_that_names_the_artifact_leaves_no_gap(cycle, monkeypatch, how):
    first = cycle.dispatch("dev", declared=False)
    cycle.finish(first, [("Bash", {"command": f"python3 gen.py > {REPORT}"}) if "shell" in how else ("Write", {"file_path": str(cycle.project / REPORT), "content": "{}"})])
    cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


def test_lanes_that_share_a_task_id_and_artifacts_are_other_groups(cycle, monkeypatch):
    cycle.dispatch("dev", lane="l1", suffix=False, declared=False)
    cycle.dispatch("dev", lane="l2", suffix=False)
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


@pytest.mark.parametrize("other", ["another artifact set", "another lane", "another task", "another role"])
def test_a_dispatch_of_another_group_is_no_gap(cycle, monkeypatch, other):
    cycle.dispatch("dev", declared=False)
    if other == "another artifact set":
        cycle.dispatch("dev", artifacts=[{"kind": "json", "path": "docs/dev/other.json", "schema": "dev-report.v2", "identity": {"task_id": TASK}}])
    elif other == "another lane":
        cycle.dispatch("dev", lane="l1")
    elif other == "another task":
        cycle.dispatch("dev", task="20261109-130000")
    else:
        cycle.dispatch("ba", artifacts=[{"kind": "json", "path": REPORT, "schema": "dev-report.v2", "identity": {"task_id": TASK}}])
    cycle.observe(monkeypatch)
    assert not gaps(cycle)


def test_no_gap_is_scored_when_the_previous_dispatchs_transcript_is_gone_and_other_gaps_still_are(cycle, monkeypatch):
    first = cycle.dispatch("dev", declared=False)
    cycle.dispatch("dev")
    (cycle.subagents / f"agent-{cycle.agent[first]}.jsonl").unlink()
    cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}], declared=False)
    later = cycle.dispatch("ba", artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.observe(monkeypatch)
    assert [r["key"] for r in gaps(cycle)] == [f"rerun_gap:{later}"]


def test_a_close_round_that_never_wrote_its_report_is_followed_by_a_gap(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa(launch=True)  # never completed: no section, no helper call
    again = cycle.close_qa()
    cycle.observe(monkeypatch)
    assert [(r["role"], r["key"]) for r in gaps(cycle)] == [("close-qa", f"rerun_gap:{again}")]


def test_running_rerun_gap_again_adds_no_row(cycle, monkeypatch):
    cycle.dispatch("dev", declared=False)
    cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    cycle.observe(monkeypatch)
    cycle.sweep(monkeypatch)
    assert len(gaps(cycle)) == 1 and len(cycle.rows()) == 1


# ---- the observer's cost: one lock, one batch, one read of the log, bounded and shared lookups ------------------------

def spy(monkeypatch, owner, name, answer=None):
    calls = []
    real = getattr(owner, name)

    def wrapper(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs) if answer is None else answer

    monkeypatch.setattr(owner, name, wrapper)
    return calls


def test_a_sweep_takes_the_lock_once_for_one_batch_and_none_when_it_has_no_row(cycle, monkeypatch):
    locks, batches = spy(monkeypatch, score_log, "locked"), spy(monkeypatch, score_log, "append_all")
    cycle.dispatch("dev")
    cycle.observe(monkeypatch)
    assert locks == batches == []
    fail_fix_pass(cycle, monkeypatch, wrote=["src/app.py"])
    cycle.observe(monkeypatch)
    assert len(locks) == 1 and len(batches) == 1 and len(batches[0][1]) == 2


def test_a_repeat_sweep_reads_the_log_once_and_writes_nothing(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a"), (TICKET, "b"), ("src/app.py", "c")])
    cycle.observe(monkeypatch)
    log = cycle.config / "logs" / "lifecycle.jsonl"
    before, reads, real = log.read_bytes(), [], Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (reads.append(1) if self == log else None) or real(self))
    cycle.observe(monkeypatch)
    assert len(reads) == 1 and log.read_bytes() == before and len(before.splitlines()) == 6


def test_one_file_in_many_bullets_is_looked_up_once_and_charged_once(cycle, monkeypatch):
    closed(cycle)
    lookups = spy(monkeypatch, obligation, "declaring_dispatch")
    cycle.close_qa([(REPORT if i % 3 else f"{REPORT}:{i}", f"bullet {i}") for i in range(100)] + [(f"`{REPORT}`", "again")])
    cycle.observe(monkeypatch)
    assert len(lookups) == 1 and cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]


def test_repeats_do_not_use_up_the_five_files_a_round_may_cite(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, f"bullet {i}") for i in range(7)] + [(TICKET, "a different file")])
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "ba", -7), ("escaped", "dev", -7), ("escaped", "qa", -3), ("escaped", "qa", -3)]


def test_a_round_looks_at_five_distinct_files_at_most(cycle, monkeypatch):
    files = [f"src/f{i}.py" for i in range(8)]
    cycle.dispatch("dev", wrote=files)
    cycle.qa()
    cycle.report("pass")
    cycle.opener("close")
    lookups = spy(monkeypatch, obligation, "declaring_dispatch")
    cycle.close_qa([(name, "a defect") for name in files])
    cycle.observe(monkeypatch)
    assert [call[1] for call in lookups] == files[:5]
    assert sum(r["event"] == "escaped" and r["role"] == "dev" for r in cycle.rows()) == 5


def test_lookups_are_shared_across_rounds_and_the_store_is_read_once_a_task(cycle, monkeypatch):
    closed(cycle)
    lookups = spy(monkeypatch, obligation, "declaring_dispatch", {"obligation": {"task_id": TASK, "role": "dev", "pipeline": "dev"}})
    scans = spy(monkeypatch, obligation, "_task_records")
    for _ in range(3):
        cycle.close_qa([(REPORT, "a"), (TICKET, "b"), ("src/app.py", "c")])
    cycle.observe(monkeypatch)
    assert sorted(call[1] for call in lookups) == sorted([REPORT, TICKET, "src/app.py"]) and len(scans) == 1


def test_a_dispatchs_write_set_is_read_once_a_sweep(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "a"), (TICKET, "b"), ("src/app.py", "c")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.dispatch("dev", wrote=["src/app.py"])
    cycle.close_qa()
    reads = spy(monkeypatch, score_events.command_span, "write_set")
    cycle.observe(monkeypatch)
    ours = [call[:2] for call in reads if len(call) == 4]  # the observer's reads; declaring_dispatch makes its own, with two arguments
    assert ours and len(ours) == len(set(ours))


def test_the_same_unfixed_defect_is_charged_once_whatever_the_rounds(cycle, monkeypatch):
    closed(cycle)
    for _ in range(4):
        cycle.close_qa([(REPORT, "still wrong")])
        cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "dev", -7), ("escaped", "qa", -3)]
    cycle.close_qa([(REPORT, "still wrong"), (TICKET, "a new file")])  # a new file is a new defect
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("escaped", "ba", -7), ("escaped", "dev", -7), ("escaped", "qa", -3), ("escaped", "qa", -3)]


def test_two_findings_fixed_in_different_rounds_are_two_catches(cycle, monkeypatch):
    closed(cycle)
    cycle.close_qa([(REPORT, "first")])
    cycle.dispatch("dev", wrote=[REPORT])
    cycle.close_qa([(TICKET, "second")])
    cycle.dispatch("ba", wrote=[TICKET], artifacts=[{"kind": "markdown", "path": TICKET, "identity_anchor": TASK}])
    cycle.close_qa()
    cycle.observe(monkeypatch)
    assert sorted(r["key"] for r in cycle.rows() if r["event"] == "close_catch") == [f"close_catch:{TASK}:{REPORT}", f"close_catch:{TASK}:{TICKET}"]


def test_a_report_that_is_a_symlink_out_of_the_project_is_not_read(cycle, monkeypatch, tmp_path):
    cycle.qa()
    path = cycle.report("pass")
    outside = tmp_path / "outside.json"
    path.rename(outside)
    path.symlink_to(outside)
    cycle.observe(monkeypatch)
    assert cycle.rows() == []


def test_a_report_that_is_a_symlink_inside_the_project_is_read(cycle, monkeypatch):
    cycle.qa()
    path = cycle.report("pass")
    real = cycle.project / "src" / "real.json"
    path.rename(real)
    path.symlink_to(real)
    cycle.observe(monkeypatch)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


def test_project_relative_paths_resolve_from_the_project_dir_when_it_is_set(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    sub = str(cycle.project / "src")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cycle.config))
    score_events.sweep(str(cycle.transcript), sub)  # the session's cwd moved into a subfolder: its docs/dev is not the project's
    assert cycle.rows() == []
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(cycle.project))
    score_events.sweep(str(cycle.transcript), sub)
    assert cycle.facts() == [("qa_first_pass", "ba", 1), ("qa_first_pass", "dev", 2)]


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


def test_a_damaged_line_in_the_middle_of_the_log_stays_and_the_new_rows_follow_it(cycle, monkeypatch):
    # was: a damaged middle line stopped the writer (the old append refused such a log). score_log.append_all passes over it.
    cycle.qa()
    cycle.report("pass")
    log = cycle.config / "logs" / "lifecycle.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"kind": "event", "key": "a"}\nnot json\n{"kind": "event", "key": "b"}\n')
    cycle.observe(monkeypatch)
    lines = log.read_text().splitlines()
    assert lines[:3] == ['{"kind": "event", "key": "a"}', "not json", '{"kind": "event", "key": "b"}']
    assert [json.loads(line)["event"] for line in lines[3:]] == ["qa_first_pass", "qa_first_pass"] and len(lines) == 5


def test_a_crash_truncated_tail_does_not_stop_recording(cycle, monkeypatch):
    cycle.qa()
    cycle.report("pass")
    log = cycle.config / "logs" / "lifecycle.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"kind": "event", "key": "a"}\n{"kind": "event", "ke')  # the process died mid-row
    cycle.observe(monkeypatch)
    lines = log.read_text().splitlines()
    assert lines[0] == '{"kind": "event", "key": "a"}' and len(lines) == 3 and all(json.loads(line) for line in lines)
    cycle.observe(monkeypatch)
    assert len(log.read_text().splitlines()) == 3


def test_a_lone_surrogate_in_a_row_does_not_lose_the_other_rows_of_the_sweep(cycle, monkeypatch):
    def odd(ctx):
        d = ctx["ds"][0]
        yield score_events._event(ctx, d, "rerun_gap", "dev", "a why with \ud800 in it", "odd:1", ref="docs/\udfff.md")
        yield score_events._event(ctx, d, "rerun_gap", "dev", "a plain one", "odd:2")

    cycle.qa()
    cycle.report("pass")
    monkeypatch.setattr(score_events, "RULES", [odd, *score_events.RULES])
    cycle.observe(monkeypatch)
    assert {r["key"] for r in cycle.rows()} >= {"odd:1", "odd:2"} and len(cycle.rows()) == 4


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
