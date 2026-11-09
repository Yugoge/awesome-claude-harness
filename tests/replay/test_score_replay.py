"""P13-2 B2: the score log after a replayed /dev cycle, and after a /close that follows it.

The real hooks run under the shipped settings in a sandbox that has its own config directory; the score
observer (hooks/posttool-close-rating.py, matcher AskUserQuestion|Agent) sweeps the active command span after
each main-agent dispatch and appends score events to the sandbox's logs/lifecycle.jsonl. The stand-in CLI
(tests/replay/agents.py, roles.py, drivers/dev.py) plays the subagents: their own transcripts hold the Write and
Edit calls the observer reads, and the lane QA's failure is a qa.failures[] entry in the shape agents/qa.md spells
(severity, location, issue, recommendation, primary_cause).

Three replays carry every assertion, each run with the driver argument `resweep=1` (tests/replay/scorelog.py:
the observer hook run once more on the final transcript, the log kept as out/score-log.jsonl):

* QA_FAIL_CLOSE: /dev (variant qa-fail: the lane's first QA fails, its dev is dispatched again, the next QA
  passes), then /close in the same session: the log gains qa_fail (dev) and qa_catch (qa), no rerun_gap.
* QA_FAIL_OTHER_FILE: the same cycle, the failure naming a file the re-dispatched dev does not edit
  (`fail_at`): qa_fail, and no qa_catch.
* FIRST_PASS: /dev variant plain: qa_first_pass for dev and ba, nothing negative.

In each, the sweep of the final transcript a second time leaves the log byte for byte as it was, and runs
without error beside the compliant run's 0 gate blocks and 0 hook errors.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re

import pytest

from hooks.lib import score_log
from tests.replay import suite

OBSERVER = "hooks/posttool-close-rating.py"
ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LANE_REPORT = re.compile(r"docs/dev/qa-report-[\w.-]+\.json")  # the lane QA's report (the BA-validation QA's is ba-qa-report-...)

QA_FAIL_CLOSE = suite.Scenario("score: /dev qa-fail, then /close", "close",
                               (("variant", "plain"), ("cycle_variant", "qa-fail"), ("resweep", "1")),
                               ("dev", "close"), 150)
OTHER_FILE = "toy/util.py"
QA_FAIL_OTHER_FILE = suite.Scenario("score: /dev qa-fail naming another file", "dev",
                                    (("variant", "qa-fail"), ("fail_at", OTHER_FILE), ("resweep", "1")),
                                    ("dev",), 110)
FIRST_PASS = suite.Scenario("score: /dev first pass", "dev", (("variant", "plain"), ("resweep", "1")), ("dev",), 90)
SCENARIOS = {"qa-fail-close": QA_FAIL_CLOSE, "qa-fail-other-file": QA_FAIL_OTHER_FILE, "first-pass": FIRST_PASS}
KEYS = {name: suite.replay_key(scn, "shipped") for name, scn in SCENARIOS.items()}


def replay(name: str):
    """A test reading the replay `name` (shared with every test that names it: one replay per session)."""
    return pytest.mark.replay(KEYS[name], SCENARIOS[name].cost)


# ---------------------------------------------------------------- what the replay left

def _jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def log_bytes(r) -> bytes:
    with open(os.path.join(r.run_dir, "score-log.jsonl"), "rb") as fh:
        return fh.read()


def events(r) -> list[dict]:
    """The log's event rows in order (legacy rows of score-update.sh carry no kind and are not events)."""
    rows = [json.loads(line) for line in log_bytes(r).decode("utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "event"]


def project(r) -> str:
    """The project directory as the replay's processes saw it (ids.json)."""
    with open(os.path.join(r.run_dir, "ids.json")) as fh:
        return json.load(fh)["layout"]["project"]


def dispatches(r) -> list[dict]:
    """Every main-agent dispatch of the replay in order, with what its subagent's own transcript says it did:
    `role` (subagent_type), `tool_use_id`, `agent_id`, `wrote` (project-relative files of its Write and Edit
    calls) and `reports` ({path: parsed content} of each qa-report it wrote)."""
    out, by_use, root = [], {}, project(r)
    mains = sorted(glob.glob(os.path.join(r.run_dir, "transcripts", "*", "*.jsonl")), key=lambda p: _jsonl(p)[0]["timestamp"])
    for main in mains:
        for rec in _jsonl(main):
            content = (rec.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use" and block.get("name") == "Agent":
                    out.append({"role": block["input"]["subagent_type"], "tool_use_id": block["id"], "main": main})
                elif block.get("type") == "tool_result" and isinstance(rec.get("toolUseResult"), dict):
                    by_use[block["tool_use_id"]] = rec["toolUseResult"].get("agentId")
    for d in out:
        d["agent_id"] = by_use[d["tool_use_id"]]
        sub = os.path.join(d["main"][:-len(".jsonl")], "subagents", f"agent-{d['agent_id']}.jsonl")
        d["wrote"], d["reports"] = [], {}
        for rec in _jsonl(sub):
            content = (rec.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use" and block.get("name") in ("Write", "Edit"):
                    rel = os.path.relpath(block["input"]["file_path"], root)
                    d["wrote"].append(rel)
                    if block["name"] == "Write" and LANE_REPORT.fullmatch(rel):
                        d["reports"][rel] = json.loads(block["input"]["content"])
    return out


def lane_qa(r) -> list[dict]:
    """The lane's final-verification QA rounds: the dispatches that wrote or edited the lane's qa-report."""
    return [d for d in dispatches(r) if d["role"] == "qa" and any(LANE_REPORT.fullmatch(p) for p in d["wrote"])]


def project_key(r) -> str:
    """S1: the first 12 hex digits of the sha256 of the project's git common directory (hooks/lib/score_log.py project_key)."""
    return hashlib.sha256(os.path.normpath(os.path.join(project(r), ".git")).encode()).hexdigest()[:12]


def task_of(r) -> str:
    return r.terminal("dev")["task"]


def clean_run(r) -> None:
    """The compliant run's terms: 0 gate blocks, 0 hook errors, every command at its terminal; and the score
    observer ran once on each main-agent dispatch's return, exit 0, nothing printed."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "a compliant run met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a compliant run met a hook error:\n" + r.explain()
    assert r.reached(), "a pipeline did not reach its terminal:\n" + r.explain()
    returns = [ev for ev in r.hook_events() if ev["event"] == "PostToolUse" and ev.get("tool") == "Agent"]
    ran = [h for ev in returns for h in ev["hooks"] if h["hook"] == OBSERVER]
    assert returns and len(ran) == len(returns) == len(dispatches(r)), (len(returns), len(ran), len(dispatches(r)))
    assert all((h["rc"], h["verdict"], h["stdout"], h["stderr"]) == (0, "ok", "", "") for h in ran), ran


def event_rows(r, shape: list[tuple]) -> list[dict]:
    """The log holds exactly the events `shape` lists ((event, role), in any order), each a well-formed row:
    kind event, this project's key, this cycle's canonical task id, the rule's points, one line of why text
    without the task id, a report path as ref, a UTC time and a key no other row has."""
    rows = events(r)
    assert sorted((e["event"], e["role"]) for e in rows) == sorted(shape), rows
    assert len({e["key"] for e in rows}) == len(rows), rows
    for e in rows:
        assert e["kind"] == "event" and e["project"] == project_key(r) and e["task_id"] == task_of(r), e
        assert e["points"] == score_log.points_for(e["event"], e["role"]), e
        assert e["why"].strip() and "\n" not in e["why"] and task_of(r) not in e["why"], e
        assert e["ref"] == f"docs/dev/qa-report-{task_of(r)}.json" and ZULU.match(e["ts"]), e
    return rows


# ---------------------------------------------------------------- B2: a QA fail, its fix, then /close

@replay("qa-fail-close")
def test_qa_fail_then_close_logs_qa_fail_for_dev_and_qa_catch_for_qa_and_no_rerun_gap(replays):
    r = replays.get(KEYS["qa-fail-close"])
    clean_run(r)
    rows = event_rows(r, [("qa_fail", "dev"), ("qa_catch", "qa")])
    fail, catch = (next(e for e in rows if e["event"] == name) for name in ("qa_fail", "qa_catch"))
    assert fail["points"] < 0 < catch["points"] and fail["ts"] <= catch["ts"]
    # what the driver played: the first QA round's failure, blamed on the dev, naming the file the dev's re-dispatch writes
    first, second = lane_qa(r)[:2]
    (report,) = first["reports"].values()
    (failure,) = report["qa"]["failures"]
    assert report["qa"]["status"] == "fail" and failure["primary_cause"] == "dev_implementation", report
    assert fail["why"] == failure["issue"], (fail, failure)
    named = failure["location"].rpartition(":")[0]
    _, dev_again = [d for d in dispatches(r) if d["role"] == "dev"]  # the cycle's dev and its re-dispatch
    assert named in dev_again["wrote"], (named, dev_again["wrote"])
    # each row stands for its own dispatch: the failing round, and the round that passed after the fix
    assert first["tool_use_id"] in fail["key"] and second["tool_use_id"] in catch["key"]
    # the QA-driven re-dispatch is not a gap
    assert not [e for e in events(r) if e["event"] == "rerun_gap"]


@replay("qa-fail-other-file")
def test_a_qa_fail_whose_fix_touches_no_named_file_gives_no_qa_catch(replays):
    r = replays.get(KEYS["qa-fail-other-file"])
    clean_run(r)
    (fail,) = event_rows(r, [("qa_fail", "dev")])
    first = lane_qa(r)[0]
    (failure,) = next(iter(first["reports"].values()))["qa"]["failures"]
    assert failure["location"].rpartition(":")[0] == OTHER_FILE and failure["primary_cause"] == "dev_implementation", failure
    assert fail["why"] == failure["issue"]
    _, dev_again = [d for d in dispatches(r) if d["role"] == "dev"]
    # the re-dispatched dev did write files (the lane's own), none of them the one the failure names
    assert dev_again["wrote"] and OTHER_FILE not in dev_again["wrote"], dev_again["wrote"]
    assert not [e for e in events(r) if e["event"] in ("qa_catch", "rerun_gap")]


@replay("first-pass")
def test_a_first_pass_cycle_gives_qa_first_pass_for_dev_and_ba_and_nothing_negative(replays):
    r = replays.get(KEYS["first-pass"])
    clean_run(r)
    rows = event_rows(r, [("qa_first_pass", "dev"), ("qa_first_pass", "ba")])
    assert all(e["points"] > 0 for e in rows) and not [e for e in events(r) if e["points"] < 0]
    (qa,) = lane_qa(r)
    assert all(qa["tool_use_id"] in e["key"] for e in rows), (qa["tool_use_id"], rows)
    assert list(qa["reports"].values())[0]["qa"]["status"] == "pass"


# ---------------------------------------------------------------- B2: replaying again adds 0 rows

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in SCENARIOS])
def test_sweeping_the_final_transcript_again_leaves_the_log_byte_for_byte_unchanged(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r)
    sweep = r.fact("score resweep")
    assert sweep and sweep.get("hooks") == 1, f"the observer hook was not run again: {sweep}"
    assert (sweep["rc"], sweep["stdout"], sweep["stderr"]) == (0, "", ""), sweep
    log = sweep["log"]
    assert log["bytes_before"] > 0 and log["unchanged"] and log["bytes_after"] == log["bytes_before"], log
    assert log["sha256_before"] == log["sha256_after"] == hashlib.sha256(log_bytes(r)).hexdigest(), log
    # the same sweep on an empty log yields rows (the silence above is not a hook that did nothing); they are
    # rows the log already holds, and for a /dev-only run, where the final span is the /dev span, all of them
    rebuilt = sweep["rebuilt"]
    assert (rebuilt["hooks"], rebuilt["rc"], rebuilt["stdout"], rebuilt["stderr"]) == (1, 0, "", ""), rebuilt
    held = {e["key"]: e for e in events(r)}
    assert all(held.get(e["key"]) == e for e in rebuilt["events"]), (rebuilt["events"], held)
    if SCENARIOS[name].pipelines == ("dev",):
        assert sorted(e["key"] for e in rebuilt["events"]) == sorted(held), (rebuilt["events"], held)

